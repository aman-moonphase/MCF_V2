"""Product Understanding schemas — one set for every provider (demo, claude, openai).

ProductProfileDraft is what the model produces from the project's sources. ProductProfile is what
MCF stores: the draft plus backend-managed fields (source references, missing fields, confidence).
Unknown information stays null / empty — it is never invented.
"""

from typing import List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field

ConfidenceLevel = Literal["low", "medium", "high"]


class ProductProfileDraft(BaseModel):
    name: Optional[str] = Field(default=None, description="Product name, exactly as given in the sources")
    description: Optional[str] = Field(default=None, description="One or two sentences describing what the product is")
    category: Optional[str] = Field(default=None, description="Product category / industry (e.g. 'bookkeeping software')")
    problem_solved: Optional[str] = Field(default=None, description="The problem the product solves for its users")
    target_audience: Optional[str] = Field(default=None, description="Who the product is for (the buyer / customer segment)")
    primary_users: List[str] = Field(default_factory=list, description="The people who actually use the product day to day")
    key_features: List[str] = Field(default_factory=list, description="Concrete features stated in the sources")
    key_benefits: List[str] = Field(default_factory=list, description="Outcomes/benefits for the user stated in the sources")
    differentiators: List[str] = Field(default_factory=list, description="What makes it different from alternatives, per the sources")
    use_cases: List[str] = Field(default_factory=list, description="Concrete situations in which the product is used")
    value_proposition: Optional[str] = Field(default=None, description="Why a customer should choose it, in one sentence")
    positioning: Optional[str] = Field(default=None, description="How the product positions itself in its market")
    market_geography: Optional[str] = Field(default=None, description="Geography / market served, only if stated")
    business_model: Optional[str] = Field(default=None, description="How it is sold or priced, only if stated")
    known_competitors: List[str] = Field(default_factory=list, description="Competitors or alternatives explicitly named in the sources")
    website_url: Optional[str] = Field(default=None, description="Product website URL, only if stated")
    constraints: List[str] = Field(default_factory=list, description="Important constraints/requirements stated in the sources")


class SourceReference(BaseModel):
    source_id: str
    name: str
    source_type: str


class ProductProfile(ProductProfileDraft):
    source_references: List[SourceReference] = Field(default_factory=list)
    missing_fields: List[str] = Field(default_factory=list)
    confidence: ConfidenceLevel = "low"


class ClarificationQuestionDraft(BaseModel):
    question: str = Field(description="A short, specific question for the product owner")
    why_it_matters: str = Field(description="Why the answer materially improves the profile / later strategy")
    fields: List[str] = Field(description="Profile field names the answer will fill")


class ClarificationQuestionsOutput(BaseModel):
    questions: List[ClarificationQuestionDraft] = Field(description="At most 5 questions; empty if nothing important is missing")


PROFILE_FIELDS: tuple[str, ...] = tuple(ProductProfileDraft.model_fields.keys())
LIST_FIELDS: frozenset[str] = frozenset(
    name for name, f in ProductProfileDraft.model_fields.items() if f.annotation == List[str]
)

# Missing any of these makes the profile materially weaker for strategy and competitor analysis.
# Ordered by importance: questions are asked in this order.
CRITICAL_FIELDS: tuple[str, ...] = (
    "name", "target_audience", "problem_solved", "key_features", "value_proposition", "category", "description",
)
# Asked about only alongside critical gaps (never on their own).
SECONDARY_ASKABLE_FIELDS: tuple[str, ...] = ("business_model", "differentiators")

MAX_QUESTIONS = 5


class ProductUnderstandingState(TypedDict, total=False):
    input_text: str
    grounding_context: dict
    current_profile: Optional[dict]
    clarifications: List[dict]  # answered questions: {question, fields, answer}
    asked_fields: List[str]  # fields already covered by any earlier question (open or answered)
    edited_fields: List[str]  # fields the user edited by hand; never overwritten
    intent: Optional[str]
    profile: Optional[dict]
    missing_fields: List[str]
    askable_fields: List[str]
    questions: List[dict]
    error: Optional[str]
    retries: int
