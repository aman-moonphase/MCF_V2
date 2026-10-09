"""Competitor Analysis schemas — shared by every provider (demo, claude, openai).

Evidence discipline:
- "observed": directly supported by a cited evidence item (refs required);
- "inferred": a reasonable interpretation of cited evidence (refs strongly expected);
- unknown: no finding at all — the section is reported as unknown instead of being filled in.

Models cite evidence with short labels the prompt assigns: "E1".."En" for evidence items,
"N" for the user's notes and "D" for the user's description. In comparisons labels are
prefixed with the competitor: "C1:E2", "C2:N".
"""

from typing import List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

FindingStatus = Literal["observed", "inferred"]


class Finding(BaseModel):
    statement: str = Field(description="One specific, evidence-grounded statement")
    status: FindingStatus = Field(description="observed = stated in the evidence; inferred = interpretation of it")
    refs: List[str] = Field(default_factory=list, description="Evidence labels supporting the statement, e.g. ['E1']")


class ContentExample(BaseModel):
    description: str = Field(description="What the piece of competitor content is")
    ref: str = Field(description="Evidence label where it appears, e.g. 'E2'")
    excerpt: str = Field(description="A short verbatim quote copied from that evidence")


class CompetitorAnalysisOutput(BaseModel):
    overview: List[Finding] = Field(default_factory=list, description="What the company/product is")
    positioning: List[Finding] = Field(default_factory=list, description="Positioning and value proposition")
    target_audience: List[Finding] = Field(default_factory=list)
    overlapping_features: List[Finding] = Field(default_factory=list, description="Features/use cases that overlap with OUR product")
    messaging_themes: List[Finding] = Field(default_factory=list)
    promotion_channels: List[Finding] = Field(default_factory=list, description="Channels referenced in the evidence (presence, not activity level)")
    content_formats: List[Finding] = Field(default_factory=list)
    content_examples: List[ContentExample] = Field(default_factory=list)
    posting_cadence: List[Finding] = Field(default_factory=list, description="ONLY if the evidence explicitly states a frequency")
    strengths: List[Finding] = Field(default_factory=list, description="Observable strengths and differentiators")
    opportunities_for_us: List[Finding] = Field(default_factory=list, description="Openings for our product suggested by the evidence")


FINDING_SECTIONS: tuple[str, ...] = (
    "overview", "positioning", "target_audience", "overlapping_features", "messaging_themes",
    "promotion_channels", "content_formats", "posting_cadence", "strengths", "opportunities_for_us",
)

SECTION_LABELS = {
    "overview": "Company/product overview",
    "positioning": "Positioning and value proposition",
    "target_audience": "Target audience",
    "overlapping_features": "Overlapping features or use cases",
    "messaging_themes": "Messaging and themes",
    "promotion_channels": "Promotion channels",
    "content_formats": "Content formats",
    "content_examples": "Content examples",
    "posting_cadence": "Posting cadence",
    "strengths": "Strengths and differentiators",
    "opportunities_for_us": "Opportunities for our product",
}


class Suggestion(BaseModel):
    suggestion: str = Field(description="A strategic idea worth considering (not a fact)")
    rationale: str = Field(description="Why, tied to the cited observations")
    refs: List[str] = Field(default_factory=list)


class ComparisonOutput(BaseModel):
    # Evidence-based observations
    similarities: List[Finding] = Field(default_factory=list)
    differences: List[Finding] = Field(default_factory=list)
    messaging_gaps: List[Finding] = Field(default_factory=list)
    # Strategic suggestions — kept separate from observations
    positioning_opportunities: List[Suggestion] = Field(default_factory=list)
    promotion_patterns_to_investigate: List[Suggestion] = Field(default_factory=list)
    evidence_needed: List[str] = Field(default_factory=list, description="What evidence is missing to judge further")


class CompetitorCandidate(BaseModel):
    name: str
    why_relevant: str
    website_url: Optional[str] = None


class CompetitorSuggestionsOutput(BaseModel):
    candidates: List[CompetitorCandidate] = Field(default_factory=list, description="At most 5 candidate competitors")


PERFORMANCE_DATA_NOTE = (
    "No engagement, reach, or campaign performance data was available for this competitor. "
    "MCF cannot tell which of their content performs best."
)


class CompetitorState(TypedDict, total=False):
    prompt_context: list  # [(label, value)] already rendered for the prompt
    allowed_refs: List[str]
    corpus: str  # all evidence text, for grounding checks
    evidence_count: int
    # Structured copy of the same project data the prompt contains, for the deterministic DemoProvider.
    demo_input: dict
    meta: dict  # run flags for grounding (e.g. limited competitor evidence)
    output: Optional[dict]
    error: Optional[str]
    retries: int
