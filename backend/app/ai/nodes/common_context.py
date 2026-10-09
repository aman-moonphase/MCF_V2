"""Project-context sections shared by stage prompts. Values come only from the current workflow state."""

from typing import List, Optional, Tuple

from ..schemas import AIState
from .common import grounding_text

ContextItem = Tuple[str, Optional[str]]


def source_context(state: AIState) -> List[ContextItem]:
    return [
        ("Source Material", state.get("input_text")),
        ("Retrieved Source Excerpts (RAG, current project only)", grounding_text(state)),
        ("Approved Content Type", state.get("approved_content_type")),
    ]


def opportunity_context(opportunity: Optional[dict]) -> List[ContextItem]:
    opportunity = opportunity or {}
    key_points = opportunity.get("keyPoints") or []
    return [
        ("Selected Content Opportunity — Title", opportunity.get("title")),
        ("Selected Content Opportunity — Summary", opportunity.get("summary")),
        ("Selected Content Opportunity — Audience", opportunity.get("potentialAudience")),
        ("Selected Content Opportunity — Key Points", "; ".join(key_points) if key_points else None),
    ]


def platforms_context(platforms: Optional[list]) -> List[ContextItem]:
    lines = []
    for p in platforms or []:
        details = ", ".join(
            part for part in (p.get("recommendedFormat"), f"{p.get('tone')} tone" if p.get("tone") else None) if part
        )
        lines.append(f"- {p.get('platform', 'Unknown')}" + (f": {details}" if details else ""))
    return [("Selected Platforms", "\n".join(lines) if lines else None)]


def angle_context(angle: Optional[dict]) -> List[ContextItem]:
    angle = angle or {}
    points = angle.get("supportingPoints") or []
    return [
        ("Selected Topic Angle — Title", angle.get("title")),
        ("Selected Topic Angle — Angle", angle.get("angle")),
        ("Selected Topic Angle — Hook", angle.get("hook")),
        ("Selected Topic Angle — Core Promise", angle.get("corePromise")),
        ("Selected Topic Angle — Supporting Points", "; ".join(points) if points else None),
    ]


def strategy_context(strategy: Optional[dict]) -> List[ContextItem]:
    strategy = strategy or {}
    talking_points = strategy.get("keyTalkingPoints") or []
    adaptations = strategy.get("platformAdaptations") or []
    return [
        ("Approved Strategy — Objective", strategy.get("objective")),
        ("Approved Strategy — Target Audience", strategy.get("targetAudience")),
        ("Approved Strategy — Core Message", strategy.get("coreMessage")),
        ("Approved Strategy — Value Proposition", strategy.get("valueProposition")),
        ("Approved Strategy — Tone", strategy.get("tone")),
        ("Approved Strategy — Format", strategy.get("format")),
        ("Approved Strategy — Hook Strategy", strategy.get("hookStrategy")),
        ("Approved Strategy — Structure", strategy.get("contentStructure")),
        ("Approved Strategy — Talking Points", "; ".join(talking_points) if talking_points else None),
        ("Approved Strategy — Call to Action", strategy.get("callToAction")),
        ("Approved Strategy — Platform Adaptations",
         "\n".join(f"- {a.get('platform')}: {a.get('format')}" for a in adaptations) if adaptations else None),
    ]
