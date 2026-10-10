"""Evaluate & Improve: the evaluator interface.

An evaluator receives the saved post and its approved context (assembled server-side, read-only) and returns
findings. It never rewrites the post and never stores anything — EvaluationService does that.

Findings have a TYPE (what we know) and a SEVERITY (how much it matters):
- problem        — confirmed by a deterministic check against the approved context or platform rules;
- recommendation — an improvement worth considering; the post is acceptable without it;
- unknown        — something the evaluator cannot verify (stated, never guessed).
Severity: high | medium | low. No scores, benchmarks, engagement predictions or performance claims.

Only the rule-based evaluator exists. A future AI evaluator must implement this interface and be selected
deliberately (it is not wired to AI_PROVIDER, so switching providers never makes evaluation a paid call).
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

FINDING_TYPES = ("problem", "recommendation", "unknown")
SEVERITIES = ("high", "medium", "low")

DIMENSIONS = (
    ("pillar_alignment", "Pillar alignment"),
    ("factual_grounding", "Factual grounding"),
    ("audience_positioning", "Audience & positioning"),
    ("readability", "Readability"),
    ("platform_readiness", "Platform readiness"),
    ("strategy_alignment", "Strategy alignment"),
)


@dataclass
class EvaluationContext:
    """Everything the evaluator may look at — all from the approved, saved state (never client input)."""
    post: Dict[str, Any]                      # the saved LinkedInPostOutput content
    version: int
    edited: bool
    product_name: str
    profile: Dict[str, Any]                   # approved profile core fields
    pillar_name: str
    pillar: Optional[Dict[str, Any]]          # approved strategy pillar (name, purpose, relation_to_product)
    strategy: Dict[str, Any]                  # primary_audience, value_proposition, messaging_direction, differentiators
    competitor: Optional[Dict[str, list]]     # competitor_findings(...) groups, or None (limited / not current)
    validation: Dict[str, Any]                # validate_post(...) on the saved post, same inputs as a manual save
    evidence: Dict[str, str]                  # evidence label -> description (from the generation snapshot)
    stale_reasons: List[str] = field(default_factory=list)  # approved context changed since generation
    policy: Any = None                        # PlatformPolicy
    competitor_limited: bool = False          # Competitor Analysis was approved with limited evidence
    # Retrieved excerpts cited by the post: ref -> {"status": current|changed|missing, "content": str}
    excerpts: Dict[str, Dict[str, Any]] = field(default_factory=dict)


class ContentEvaluator(Protocol):
    name: str  # stored with every result, e.g. "rules-v1"
    mode: str  # "rule-based"; an AI evaluator would declare itself

    def evaluate(self, context: EvaluationContext) -> Dict[str, Any]:
        """Return {"overall": {...}, "dimensions": [...], "counts": {...}, "about": str}."""
        ...
