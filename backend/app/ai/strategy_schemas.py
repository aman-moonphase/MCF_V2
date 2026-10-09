"""Promotion Strategy schema — one schema for every provider (demo, claude, openai).

Every major recommendation carries a `basis` saying where it comes from:
- competitor_observed: an observed competitor pattern (must cite competitor evidence, e.g. "C1:E2");
- evidence_inferred: an insight inferred from the available competitor evidence/comparison;
- product_profile: the approved Product Profile and its audience needs (cite e.g. "profile:target_audience");
- hypothesis: a new strategic idea that has to be tested.
"""

from typing import List, Literal

from pydantic import BaseModel, Field

from .schemas import ContentTypeEnum

Basis = Literal["competitor_observed", "evidence_inferred", "product_profile", "hypothesis"]
Confidence = Literal["low", "medium", "high"]


class Grounding(BaseModel):
    basis: Basis = Field(description="Where this recommendation comes from")
    refs: List[str] = Field(default_factory=list, description="Supporting references, e.g. 'C1:E2' or 'profile:target_audience'")
    confidence: Confidence = Field(default="medium")


class ExecutiveSummary(BaseModel):
    positioning: str = Field(description="How the product should be positioned")
    main_opportunity: str = Field(description="The main promotion opportunity")
    primary_recommendation: str = Field(description="The single most important recommendation")
    grounding: Grounding


class AudiencePositioning(BaseModel):
    primary_audience: str
    problems_and_needs: List[str] = Field(default_factory=list)
    value_proposition: str
    differentiators: List[str] = Field(default_factory=list)
    messaging_direction: str
    grounding: Grounding


class ContentPillar(BaseModel):
    name: str
    purpose: str
    relation_to_product: str = Field(description="How it relates to the Product Profile and the audience")
    grounding: Grounding


class ChannelRecommendation(BaseModel):
    channel: str
    priority: Literal["primary", "secondary"]
    rationale: str
    formats: List[str] = Field(default_factory=list, description="Content formats that could work on this channel")
    grounding: Grounding


class ContentDirection(BaseModel):
    primary_content_type: ContentTypeEnum = Field(description="The ONE content type for the MVP")
    reason: str
    alternatives: List[ContentTypeEnum] = Field(default_factory=list, description="One or two for later; NOT used by the MVP")
    subject_areas: List[str] = Field(default_factory=list)
    messaging_angles: List[str] = Field(default_factory=list)
    grounding: Grounding


class PublishingCadence(BaseModel):
    frequency: str
    rationale: str
    planning_horizon: str
    is_hypothesis: bool = Field(default=True, description="True unless measured performance data supports it")
    grounding: Grounding


class RoadmapItem(BaseModel):
    sequence: int = Field(description="Order in the campaign, starting at 1")
    timing: str = Field(description="Relative timing, e.g. 'Week 1'")
    objective: str
    topic: str
    channel: str
    format: str
    audience: str
    success_evaluation: str
    grounding: Grounding


class MeasurementItem(BaseModel):
    indicator: str
    what_to_measure: str
    why: str
    grounding: Grounding


class PromotionStrategyOutput(BaseModel):
    executive_summary: ExecutiveSummary
    audience: AudiencePositioning
    content_pillars: List[ContentPillar] = Field(default_factory=list, description="2-5 recurring themes")
    channels: List[ChannelRecommendation] = Field(default_factory=list)
    content_direction: ContentDirection
    cadence: PublishingCadence
    roadmap: List[RoadmapItem] = Field(default_factory=list)
    measurement: List[MeasurementItem] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list, description="What is missing and how it limits the strategy")


EDITABLE_SECTIONS = (
    "executive_summary", "audience", "content_pillars", "channels", "content_direction", "cadence", "roadmap", "measurement",
)
