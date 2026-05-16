"""
Pydantic schemas for both stages of the Sales Intelligence pipeline.

Stage 1 (Research Agent) outputs `FactSheet` — a STRUCTURED but PURELY FACTUAL
collection of verified data points with explicit sources. NO inference.

Stage 2 (Analyst Agent) consumes `FactSheet` and outputs `SalesIntelOutput` —
the final analysis that references back to fact_ids from stage 1.

Why this split: it forces the model to "show its work". If a recommendation in
stage 2 cannot point to a fact_id in stage 1, it gets flagged as inferential
(low confidence) or pushed into `data_gaps` instead of being fabricated.
"""

from typing import List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# STAGE 1 — Research Agent fact sheet
# ---------------------------------------------------------------------------


class Fact(BaseModel):
    """A single verified data point with provenance."""

    fact_id: str = Field(
        description="Short unique ID like F1, F2... used by stage 2 to cite this fact."
    )
    statement: str = Field(
        description="The factual claim, as concise as possible. No interpretation."
    )
    source_type: Literal[
        "linkedin_text",       # Pasted by user
        "company_website",     # Scraped About/Careers
        "google_search",       # Native grounding result
        "user_freeform",       # User's freeform notes
    ]
    source_detail: str = Field(
        description="URL, page section, or note origin so the user can verify."
    )
    recency: Optional[str] = Field(
        default=None,
        description="ISO date or human label like '2024-Q3' if known.",
    )


class FactSheet(BaseModel):
    """Stage 1 output. Pure facts, no analysis."""

    target_person: List[Fact] = Field(
        description="Facts about the individual candidate (role, tenure, education, public statements, etc.)."
    )
    target_company: List[Fact] = Field(
        description="Facts about the company (size, stage, recent news, strategy signals, hiring patterns)."
    )
    role_context: List[Fact] = Field(
        description="Facts about what this role typically owns at this type of company."
    )
    notable_signals: List[Fact] = Field(
        description="Anything unusual or differentiating worth surfacing (awards, controversies, pivots, public talks)."
    )
    coverage_assessment: str = Field(
        description="Honest 1-2 sentence assessment of how much we actually learned vs. what is still unknown."
    )


# ---------------------------------------------------------------------------
# STAGE 2 — Sales Analyst final output
# ---------------------------------------------------------------------------


Confidence = Literal["high", "medium", "low"]


class CommercialPriority(BaseModel):
    """JTBD framing: what is this person hired to do, therefore what do they care about?"""

    jtbd_statement: str = Field(
        description="Format: 'They are hired to [job], so they care about [outcome].'"
    )
    priority: str = Field(description="Concrete priority, specific to this person and company.")
    evidence_refs: List[str] = Field(
        description="fact_ids from the FactSheet that support this. Empty list is NOT allowed — if no facts support it, omit the priority entirely."
    )
    confidence: Confidence


class PainPoint(BaseModel):
    pain: str
    why_it_matters_for_them: str = Field(
        description="Why a person in this role at this company would feel this pain."
    )
    evidence_refs: List[str]
    confidence: Confidence


class MotivationFactor(BaseModel):
    """Push/Pull analysis — why might they leave (push) or join (pull)."""

    factor: str
    type: Literal["push", "pull"]
    evidence_refs: List[str]
    confidence: Confidence


class ConversationAngle(BaseModel):
    """Challenger Sale: an insight that reframes how they see their world."""

    angle: str = Field(
        description="The provocative insight — what they probably haven't considered."
    )
    opening_question: str = Field(
        description="A question the BD can lead with, designed to test the angle."
    )
    why_it_resonates: str
    evidence_refs: List[str]


class TalkingPoint(BaseModel):
    """Specific, citable things about them — 'I saw you X' material."""

    point: str
    source: str = Field(description="URL or specific reference so BD can verify before using.")
    how_to_use_naturally: str = Field(
        description="One sentence on how to weave this in without sounding stalkerish."
    )


class OutreachDraft(BaseModel):
    type: Literal["linkedin_inmail", "follow_up_after_no_reply"]
    subject_or_opener: str = Field(
        description="LinkedIn InMail subject OR follow-up message opener."
    )
    body: str = Field(description="Full message body. Under 300 chars for InMail.")
    rationale: str = Field(
        description="2-line explanation of strategic choice. Useful for BD to learn."
    )


class ExploratoryQuestion(BaseModel):
    question: str
    category: Literal["career_exploration", "expertise_validation"]
    rationale: str = Field(description="What this question is designed to surface.")


class Source(BaseModel):
    """Master source registry — every fact_id in evidence_refs must trace back here."""

    fact_id: str
    citation: str
    url: Optional[str] = None
    snippet: Optional[str] = Field(
        default=None, description="Short quote/paraphrase under 15 words."
    )


class DataGap(BaseModel):
    """When data is insufficient, surface this INSTEAD of guessing."""

    missing_info: str = Field(description="What specifically is missing.")
    why_needed: str = Field(description="What analysis it would unlock.")
    suggestion_for_user: str = Field(
        description="Concrete next step: 'Paste their full LinkedIn About section' / 'Share a recent talk transcript'."
    )


class SalesIntelOutput(BaseModel):
    """The final, structured commercial intelligence handed to the BD."""

    snapshot: str = Field(
        description="One-sentence summary: who this person is, where they are, what stands out."
    )
    inferred_role_context: str = Field(
        description="Plain-English description of likely scope, decision authority, and KPIs."
    )
    commercial_priorities: List[CommercialPriority]
    likely_pain_points: List[PainPoint]
    motivation_hypotheses: List[MotivationFactor]
    conversation_angles: List[ConversationAngle]
    talking_points_about_them: List[TalkingPoint]
    outreach_drafts: List[OutreachDraft]
    exploratory_questions: List[ExploratoryQuestion]
    red_flags: List[str] = Field(
        description="Topics or framings to AVOID. E.g., 'Don't mention competitor X — recently litigated against them.'"
    )
    sources: List[Source]
    data_gaps: List[DataGap]
    overall_confidence: Confidence
