"""
Streamlit app for the Sales Intelligence Assistant.

Run with:
    streamlit run app.py

The UI walks through:
  1. Input form (LinkedIn text, company URL, freeform notes) + future upload stubs
  2. Staged loading messages mapped to the two-stage pipeline
  3. Rendered sections of the analysis with citation chips
  4. Refinement panel (additional notes + focused regenerate)
"""

from __future__ import annotations

import json
import time
from typing import Optional

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from agents import UserInputs, run_analyst_agent, run_research_agent
from schema import FactSheet, SalesIntelOutput
from scraper import ScrapeResult, scrape_company_site

st.set_page_config(
    page_title="Sales Intelligence Assistant",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------------

if "fact_sheet" not in st.session_state:
    st.session_state.fact_sheet: Optional[FactSheet] = None
if "analysis" not in st.session_state:
    st.session_state.analysis: Optional[SalesIntelOutput] = None
if "scrape_result" not in st.session_state:
    st.session_state.scrape_result: Optional[ScrapeResult] = None


# ---------------------------------------------------------------------------
# Sidebar — methodology brief (always visible for demo context)
# ---------------------------------------------------------------------------

with st.sidebar:
    st.markdown("### How this works")
    st.markdown(
        """
**Two-stage pipeline**

1. **Research Agent** (Gemini 2.5 Flash)
   Pulls facts from your inputs + Google Search grounding + scraped About/Careers pages. **No inference.**

2. **Sales Analyst** (Gemini 2.5 Pro + thinking)
   Applies **JTBD → Challenger → Push/Pull** frameworks. Every claim cites a fact_id.

**Anti-hallucination spine**: stage 2 cannot see the web. It reasons only from the fact sheet, so it cannot invent sources.

When facts are missing, results go into **data_gaps** instead of being guessed.
        """
    )
    st.divider()
    st.caption("Prototype scope: single user, no history. CRM + Postgres integration documented in METHODOLOGY.md.")


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("🎯 Sales Intelligence Assistant")
st.markdown(
    "Pre-conversation intelligence for engaging Director / VP / Partner-level "
    "consulting professionals."
)


# ---------------------------------------------------------------------------
# Input form
# ---------------------------------------------------------------------------

with st.container(border=True):
    st.markdown("##### Provide at least one input")

    col1, col2 = st.columns([3, 2])
    with col1:
        linkedin_text = st.text_area(
            "LinkedIn profile text (copy About + Experience sections)",
            height=200,
            placeholder="Paste the public LinkedIn content here...",
        )
    with col2:
        company_url = st.text_input(
            "Company website URL",
            placeholder="https://example.com",
            help="We'll scrape About + Careers pages.",
        )
        freeform_notes = st.text_area(
            "Freeform notes (optional)",
            height=120,
            placeholder="Anything else you know about the person or context...",
        )

    # Stubs for future PDF/JPG upload — explicit "coming soon"
    with st.expander("📎 File upload (coming soon)"):
        st.file_uploader(
            "PDF or screenshot (disabled in prototype)",
            type=["pdf", "jpg", "jpeg", "png"],
            disabled=True,
        )
        st.caption(
            "Production version will OCR screenshots and extract text from "
            "uploaded CV PDFs. Disabled for prototype to keep scope tight."
        )

    analyse_clicked = st.button(
        "Analyse", type="primary", use_container_width=True
    )


# ---------------------------------------------------------------------------
# Pipeline execution
# ---------------------------------------------------------------------------


def run_pipeline(inputs: UserInputs) -> None:
    progress = st.progress(0, text="Starting...")

    # Step 1: scrape (if URL provided)
    if inputs.company_url:
        progress.progress(15, text="Fetching company signals from the last 6 months...")
        scrape_result = scrape_company_site(inputs.company_url)
        st.session_state.scrape_result = scrape_result
    else:
        scrape_result = None

    # Step 2: research agent
    progress.progress(35, text="Mapping role context and decision authority...")
    fact_sheet = run_research_agent(inputs, scrape_result=scrape_result)
    st.session_state.fact_sheet = fact_sheet

    # Step 3: analyst agent
    progress.progress(70, text="Drafting conversation angles...")
    analysis = run_analyst_agent(fact_sheet)
    st.session_state.analysis = analysis

    progress.progress(100, text="Done.")
    time.sleep(0.4)
    progress.empty()


def run_refinement(extra_notes: Optional[str], focus: Optional[str]) -> None:
    if st.session_state.fact_sheet is None:
        st.warning("Run an analysis first.")
        return
    progress = st.progress(0, text="Refining analysis...")
    progress.progress(50, text="Re-running analyst with new focus...")
    analysis = run_analyst_agent(
        st.session_state.fact_sheet,
        regen_focus=focus,
        extra_user_notes=extra_notes,
    )
    st.session_state.analysis = analysis
    progress.progress(100, text="Done.")
    time.sleep(0.3)
    progress.empty()


if analyse_clicked:
    inputs = UserInputs(
        linkedin_text=linkedin_text.strip() or None,
        company_url=company_url.strip() or None,
        freeform_notes=freeform_notes.strip() or None,
    )
    if inputs.is_empty():
        st.error("Please provide at least one input.")
    else:
        try:
            run_pipeline(inputs)
        except Exception as exc:
            st.error(f"Pipeline failed: {exc}")


# ---------------------------------------------------------------------------
# Results rendering
# ---------------------------------------------------------------------------


def _conf_color(level: str) -> str:
    return {"high": "🟢", "medium": "🟡", "low": "🔴"}.get(level, "⚪")


def _fact_chip(fact_id: str) -> str:
    return f"`{fact_id}`"


def render_analysis(analysis: SalesIntelOutput) -> None:
    # Snapshot
    st.markdown("## Snapshot")
    st.info(analysis.snapshot)
    st.markdown(f"**Role context.** {analysis.inferred_role_context}")
    st.caption(f"Overall confidence: {_conf_color(analysis.overall_confidence)} {analysis.overall_confidence}")

    # Two-column layout for major sections
    left, right = st.columns(2)

    with left:
        st.markdown("## 🎯 Commercial Priorities (JTBD)")
        for p in analysis.commercial_priorities:
            with st.container(border=True):
                st.markdown(f"_{p.jtbd_statement}_")
                st.markdown(f"**{p.priority}**")
                st.caption(
                    f"{_conf_color(p.confidence)} {p.confidence} · refs: "
                    + ", ".join(_fact_chip(f) for f in p.evidence_refs)
                )

        st.markdown("## 🩹 Likely Pain Points")
        for pp in analysis.likely_pain_points:
            with st.container(border=True):
                st.markdown(f"**{pp.pain}**")
                st.markdown(pp.why_it_matters_for_them)
                st.caption(
                    f"{_conf_color(pp.confidence)} {pp.confidence} · refs: "
                    + ", ".join(_fact_chip(f) for f in pp.evidence_refs)
                )

        st.markdown("## 🔄 Motivation Hypotheses (Push / Pull)")
        for m in analysis.motivation_hypotheses:
            icon = "⬅️ Push" if m.type == "push" else "➡️ Pull"
            with st.container(border=True):
                st.markdown(f"**{icon}** — {m.factor}")
                st.caption(
                    f"{_conf_color(m.confidence)} {m.confidence} · refs: "
                    + ", ".join(_fact_chip(f) for f in m.evidence_refs)
                )

    with right:
        st.markdown("## 💡 Conversation Angles (Challenger)")
        for a in analysis.conversation_angles:
            with st.container(border=True):
                st.markdown(f"**Insight.** {a.angle}")
                st.markdown(f"**Opening question.** _{a.opening_question}_")
                st.caption(f"Why it lands: {a.why_it_resonates}")
                st.caption("refs: " + ", ".join(_fact_chip(f) for f in a.evidence_refs))

        st.markdown("## 📌 Talking Points About Them")
        for tp in analysis.talking_points_about_them:
            with st.container(border=True):
                st.markdown(f"**{tp.point}**")
                st.caption(f"How to use: {tp.how_to_use_naturally}")
                st.caption(f"Source: {tp.source}")

    # Outreach drafts — full width with copy buttons
    st.markdown("## ✉️ Outreach Drafts")
    for i, draft in enumerate(analysis.outreach_drafts):
        with st.container(border=True):
            type_label = "LinkedIn InMail" if draft.type == "linkedin_inmail" else "Follow-up (after no reply)"
            st.markdown(f"##### {type_label}")
            st.markdown(f"**Subject/opener.** {draft.subject_or_opener}")
            st.code(draft.body, language=None)
            st.caption(f"Strategy: {draft.rationale}")

    # Exploratory questions
    st.markdown("## ❓ Exploratory Questions for the First Call")
    career_qs = [q for q in analysis.exploratory_questions if q.category == "career_exploration"]
    expertise_qs = [q for q in analysis.exploratory_questions if q.category == "expertise_validation"]
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Career exploration**")
        for q in career_qs:
            with st.container(border=True):
                st.markdown(q.question)
                st.caption(q.rationale)
    with c2:
        st.markdown("**Expertise validation**")
        for q in expertise_qs:
            with st.container(border=True):
                st.markdown(q.question)
                st.caption(q.rationale)

    # Red flags
    if analysis.red_flags:
        st.markdown("## 🚫 Red Flags / Things to Avoid")
        for rf in analysis.red_flags:
            st.warning(rf)

    # Data gaps — honest about what we don't know
    if analysis.data_gaps:
        st.markdown("## 📭 Data Gaps")
        st.caption("Where the analysis was thin. Provide these and re-run for sharper output.")
        for gap in analysis.data_gaps:
            with st.container(border=True):
                st.markdown(f"**Missing.** {gap.missing_info}")
                st.markdown(f"**Why it matters.** {gap.why_needed}")
                st.markdown(f"**Suggestion.** {gap.suggestion_for_user}")

    # Sources
    with st.expander(f"📚 Sources ({len(analysis.sources)})"):
        for s in analysis.sources:
            line = f"**{s.fact_id}** — {s.citation}"
            if s.url:
                line += f" · [{s.url}]({s.url})"
            st.markdown(line)
            if s.snippet:
                st.caption(f"_{s.snippet}_")

    # Raw JSON download
    with st.expander("🧰 Raw JSON output"):
        st.download_button(
            "Download as JSON",
            data=json.dumps(analysis.model_dump(), indent=2, ensure_ascii=False),
            file_name="sales_intel_output.json",
            mime="application/json",
        )
        st.json(analysis.model_dump())


# ---------------------------------------------------------------------------
# Refinement panel (bottom)
# ---------------------------------------------------------------------------


def render_refinement_panel() -> None:
    st.divider()
    st.markdown("### 🔁 Refine the analysis")
    with st.form("refine_form"):
        extra_notes = st.text_area(
            "Add more context (e.g., something the candidate said publicly that you found)",
            placeholder="Optional. Will be passed to the analyst on regenerate.",
        )
        focus = st.radio(
            "Optional focus area for regeneration",
            options=[
                None,
                "career_motivations",
                "commercial_impact",
                "objection_handling",
            ],
            format_func=lambda x: {
                None: "No specific focus",
                "career_motivations": "Career motivations (why they might move)",
                "commercial_impact": "Commercial impact (what they could deliver)",
                "objection_handling": "Objection handling (likely pushback)",
            }[x],
            horizontal=False,
        )
        submitted = st.form_submit_button("Regenerate", type="secondary")
        if submitted:
            try:
                run_refinement(extra_notes.strip() or None, focus)
            except Exception as exc:
                st.error(f"Refinement failed: {exc}")


# ---------------------------------------------------------------------------
# Final layout — render results if available
# ---------------------------------------------------------------------------

if st.session_state.analysis is not None:
    render_analysis(st.session_state.analysis)
    render_refinement_panel()
elif st.session_state.fact_sheet is not None:
    st.info("Fact sheet collected but no analysis yet. Click Analyse again.")
