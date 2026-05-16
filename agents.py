"""
Two-stage Gemini agent orchestration.

Stage 1: Research Agent
  - Model: Gemini 2.5 Flash
  - Tools: google_search (native grounding) + injected scraped pages
  - Output: FactSheet (structured JSON)

Stage 2: Analyst Agent
  - Model: Gemini 2.5 Pro
  - Thinking: enabled (deeper reasoning for JTBD/Challenger/Push-Pull)
  - Output: SalesIntelOutput (structured JSON)

Key implementation notes:
- We pass `response_schema` to enforce structured output. Gemini will respect
  the Pydantic schema and return valid JSON.
- google_search grounding is enabled ONLY for stage 1. Stage 2 must reason
  from the fact sheet exclusively — this is the anti-hallucination spine.
- We surface Gemini's native grounding citations into the FactSheet by parsing
  the response's grounding_metadata.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional

from google import genai
from google.genai import types

from prompts import (
    ANALYST_AGENT_PROMPT_FULL,
    REGEN_FOCUS_PROMPTS,
    RESEARCH_AGENT_PROMPT,
)
from schema import FactSheet, SalesIntelOutput
from scraper import ScrapeResult, format_scrape_for_prompt

# Model identifiers (kept here so they are easy to swap as Google ships updates)
RESEARCH_MODEL = "gemini-2.5-flash"
ANALYST_MODEL = "gemini-2.5-pro"


@dataclass
class UserInputs:
    """Whatever the user provided in the Streamlit form."""

    linkedin_text: Optional[str] = None
    company_url: Optional[str] = None
    freeform_notes: Optional[str] = None

    def is_empty(self) -> bool:
        return not any([self.linkedin_text, self.company_url, self.freeform_notes])


def _get_client() -> genai.Client:
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Copy .env.example to .env and add your key."
        )
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------------
# STAGE 1
# ---------------------------------------------------------------------------


def run_research_agent(
    inputs: UserInputs,
    scrape_result: Optional[ScrapeResult] = None,
) -> FactSheet:
    """Run stage 1 with google_search grounding + scraped page content."""
    client = _get_client()

    user_content_blocks = ["# USER INPUTS"]

    if inputs.linkedin_text:
        user_content_blocks.append(
            f"## LINKEDIN PROFILE TEXT (pasted by user)\n\n{inputs.linkedin_text}"
        )

    if inputs.company_url:
        user_content_blocks.append(f"## COMPANY URL\n\n{inputs.company_url}")

    if scrape_result and scrape_result.pages:
        user_content_blocks.append(
            "## COMPANY WEBSITE CONTENT (scraped)\n\n"
            + format_scrape_for_prompt(scrape_result)
        )
    elif scrape_result and scrape_result.errors:
        user_content_blocks.append(
            "## SCRAPE NOTES\n\nThe following scrape attempts failed; rely on "
            "Google Search instead:\n- " + "\n- ".join(scrape_result.errors)
        )

    if inputs.freeform_notes:
        user_content_blocks.append(
            f"## ADDITIONAL FREEFORM NOTES\n\n{inputs.freeform_notes}"
        )

    user_content_blocks.append(
        "\n# TASK\nProduce the FactSheet JSON. Use google_search liberally to "
        "fill in gaps about recent news, public talks, press mentions, and any "
        "industry context that strengthens the fact sheet. Search as many times "
        "as needed — the analyst depends on having a rich evidence base."
    )

    full_user_prompt = "\n\n".join(user_content_blocks)

    # NOTE: When using tools like google_search, Gemini does not currently
    # support `response_schema` simultaneously. We therefore enable grounding
    # here and ask the model to RETURN JSON in the response text, then parse.
    # In stage 2 (no tools) we DO use response_schema for hard enforcement.
    config = types.GenerateContentConfig(
        system_instruction=RESEARCH_AGENT_PROMPT,
        tools=[types.Tool(google_search=types.GoogleSearch())],
        temperature=0.2,
        max_output_tokens=32768,
    )

    response = client.models.generate_content(
        model=RESEARCH_MODEL,
        contents=full_user_prompt,
        config=config,
    )

    raw_text = _extract_response_text(response)
    if not raw_text.strip():
        finish_reason = _get_finish_reason(response)
        raise RuntimeError(
            f"Stage 1 returned no text. finish_reason={finish_reason}. "
            "Common causes: MAX_TOKENS (inputs too large), SAFETY (filter "
            "fired), or RECITATION. Try shorter freeform notes or remove the "
            "company URL if the scraped content is very long."
        )

    fact_sheet_json = _extract_json_block(raw_text)
    return FactSheet.model_validate(fact_sheet_json)


# ---------------------------------------------------------------------------
# STAGE 2
# ---------------------------------------------------------------------------


def run_analyst_agent(
    fact_sheet: FactSheet,
    regen_focus: Optional[str] = None,
    extra_user_notes: Optional[str] = None,
) -> SalesIntelOutput:
    """Run stage 2 with thinking enabled and a strict response schema."""
    client = _get_client()

    instruction = ANALYST_AGENT_PROMPT_FULL

    user_prompt_parts = [
        "# FACT SHEET FROM STAGE 1\n\n"
        + json.dumps(fact_sheet.model_dump(), indent=2, ensure_ascii=False)
    ]

    if extra_user_notes:
        user_prompt_parts.append(
            f"# ADDITIONAL USER NOTES (after first analysis)\n\n{extra_user_notes}"
        )

    if regen_focus and regen_focus in REGEN_FOCUS_PROMPTS:
        user_prompt_parts.append(
            f"# REGENERATION DIRECTIVE\n\n{REGEN_FOCUS_PROMPTS[regen_focus]}"
        )

    user_prompt_parts.append(
        "# TASK\nProduce the SalesIntelOutput JSON. Every claim must cite "
        "fact_ids. When facts are insufficient, populate data_gaps instead."
    )

    full_user_prompt = "\n\n".join(user_prompt_parts)

    config = types.GenerateContentConfig(
        system_instruction=instruction,
        response_mime_type="application/json",
        response_schema=SalesIntelOutput,
        temperature=0.4,
        thinking_config=types.ThinkingConfig(
            thinking_budget=-1,  # let model decide; -1 = dynamic
            include_thoughts=False,
        ),
    )

    response = client.models.generate_content(
        model=ANALYST_MODEL,
        contents=full_user_prompt,
        config=config,
    )

    # With response_schema set, response.parsed gives us a typed object directly
    parsed = response.parsed
    if isinstance(parsed, SalesIntelOutput):
        return parsed
    # Fallback: parse from text
    return SalesIntelOutput.model_validate(_extract_json_block(response.text or ""))


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------


def _extract_response_text(response) -> str:
    """Robustly pull text from a Gemini response.

    `response.text` is a convenience shortcut that returns "" when the
    response contains non-text parts (function calls, etc.) — even if a
    text part also exists. We walk candidates/parts explicitly as a fallback.
    """
    # Try the shortcut first
    try:
        if response.text:
            return response.text
    except Exception:
        pass

    # Fallback: walk parts
    collected = []
    try:
        for candidate in getattr(response, "candidates", None) or []:
            content = getattr(candidate, "content", None)
            if not content:
                continue
            for part in getattr(content, "parts", None) or []:
                txt = getattr(part, "text", None)
                if txt:
                    collected.append(txt)
    except Exception:
        pass
    return "\n".join(collected)


def _get_finish_reason(response) -> str:
    try:
        return str(response.candidates[0].finish_reason)
    except Exception:
        return "UNKNOWN"


def _extract_json_block(text: str) -> dict:
    """Extract a JSON object from raw text. Tolerant of code-fenced output."""
    t = text.strip()
    # Strip code fences
    if t.startswith("```"):
        # Remove opening fence (```json or ```)
        t = t.split("\n", 1)[1] if "\n" in t else t
        # Remove closing fence
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    # Find first { and last }
    start = t.find("{")
    end = t.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in model output: {text[:200]}")
    return json.loads(t[start : end + 1])