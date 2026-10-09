"""Promotion Strategy LangGraph workflow: generate (configured provider) → ground (strategy_grounding) → END."""

from ..strategy_grounding import ground_strategy
from ..strategy_schemas import PromotionStrategyOutput
from .competitor_graph import _build_graph, _graph, _run

STRATEGY_INSTRUCTIONS = """
Write a PRODUCT-LEVEL promotion plan (not a brief for a single post) using only the approved Product Profile and
the competitor intelligence above.
For every section, set `grounding.basis` honestly:
- competitor_observed: an observed competitor pattern — cite the competitor evidence label (e.g. "C1:E2").
- evidence_inferred: an insight inferred from the competitor evidence/comparison — cite it.
- product_profile: from the Product Profile and audience needs — cite fields like "profile:target_audience".
- hypothesis: a new idea that must be tested.
Rules:
- Differentiate; do not just copy competitors. Use competitor gaps and our differentiators.
- Never claim a competitor's content performs well: no performance data is available.
- Never invent statistics, engagement numbers, conversion rates, prices, or predicted results.
- Cadence is a recommendation to test (is_hypothesis = true).
- content_direction.primary_content_type is ONE of: Video, Image, Carousel, Article, Newsletter, Social Post.
  Alternatives (max 2) are for later and must differ from it. Every roadmap item uses the primary type.
- 2-5 content pillars; 1 primary channel plus optional secondary channels; a roadmap of 4-8 steps with relative timing.
- Measurement: indicators and what to measure — no target numbers.
- `limitations`: what evidence is missing and how it lowers confidence.
"""


async def run_promotion_strategy(state: dict) -> dict:
    graph = _graph("strategy", lambda: _build_graph(
        PromotionStrategyOutput, "Promotion Strategy", STRATEGY_INSTRUCTIONS,
        lambda s, out: ground_strategy(out, s.get("allowed_refs") or [], s.get("corpus") or "", bool((s.get("meta") or {}).get("limited"))),
    ))
    return await _run(graph, state, "Promotion Strategy AI Error")
