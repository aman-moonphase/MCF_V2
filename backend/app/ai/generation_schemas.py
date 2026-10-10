"""LinkedIn Social Post generation schema — shared by demo, claude and openai.

Evidence labels the prompt assigns:
- "S1".."Sn": the current project's own source material (full source, retrieved excerpts);
- "P:<field>": a field of the approved Product Profile (e.g. "P:key_features");
- "C1:E2" etc.: competitor evidence — context for differentiation, never a fact about OUR product.
"""

from typing import List, Literal, Optional, TypedDict

from pydantic import BaseModel, Field


class PostClaim(BaseModel):
    text: str = Field(description="A statement made in the post")
    kind: Literal["product_fact", "creative", "competitor_context"] = Field(
        description="product_fact = factual claim about OUR product (must cite S*/P:*); creative = messaging, not a fact; "
                    "competitor_context = positioning informed by competitor evidence (not stated as fact)")
    refs: List[str] = Field(default_factory=list)


class LinkedInPostOutput(BaseModel):
    hook: str = Field(description="The selected opening line")
    alternative_hooks: List[str] = Field(description="Exactly three alternative opening lines, all different from the hook")
    body: str = Field(description="The post body after the hook (no hashtags, no CTA)")
    cta: str = Field(description="One call to action")
    hashtags: List[str] = Field(default_factory=list, description="Relevant hashtags, at most 5, each starting with #")
    claims: List[PostClaim] = Field(default_factory=list, description="Every factual product claim used in the post, with evidence")
    pillar: str = Field(description="The content pillar this post serves")
    strategy_alignment: str = Field(description="How the post follows the approved strategy and positioning")
    limitations: List[str] = Field(default_factory=list, description="What could not be supported or was left out")


class GenerationState(TypedDict, total=False):
    prompt_context: list
    allowed_refs: List[str]
    corpus: str
    meta: dict  # product_name, pillar, forbidden_names, competitor_texts, policy limits
    demo_input: dict
    output: Optional[dict]
    validation: Optional[dict]
    error: Optional[str]
    retries: int
