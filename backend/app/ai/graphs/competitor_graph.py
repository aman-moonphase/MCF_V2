"""Competitor Analysis LangGraph workflows.

Each run is: generate (structured, via the configured provider) → ground (deterministic evidence
checks, see app/ai/competitor_grounding.py) → END. Generation errors retry up to MAX_RETRIES.
"""

from typing import Any, Callable, Dict, Type

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel

from ..competitor_schemas import (
    ComparisonOutput, CompetitorAnalysisOutput, CompetitorState, CompetitorSuggestionsOutput,
)
from ..nodes.common import MAX_RETRIES, call_structured, generation_failure, retry_feedback
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider

STAGE = "competitor-analysis"

ANALYSIS_INSTRUCTIONS = """
Analyse ONE competitor using only the evidence above. Cite evidence by its label (E1, E2, N, D).
Rules:
- status "observed" = directly stated in the cited evidence. status "inferred" = your interpretation of it.
- If the evidence says nothing about a section, return an empty list for it. Empty is correct; guessing is not.
- A company website shows what they SAY. It does not prove posting frequency, engagement, ad spend, or results.
  Do not claim to know what performs best.
- `promotion_channels` lists channels the evidence references (e.g. a linked LinkedIn page) — presence, not activity level.
- `posting_cadence` only when the evidence explicitly states a frequency; otherwise leave it empty.
- Never invent numbers, rankings, prices, schedules, customer counts, or statistics.
- `content_examples.excerpt` must be copied verbatim from the cited evidence.
- `overlapping_features` and `opportunities_for_us` compare against OUR approved Product Profile.
"""

COMPARISON_INSTRUCTIONS = """
Compare OUR approved Product Profile with the analysed competitors. Cite competitor evidence with
prefixed labels exactly as given (e.g. "C1:E2", "C2:N").
- similarities / differences / messaging_gaps are OBSERVATIONS: only what the analyses and evidence show.
- positioning_opportunities / promotion_patterns_to_investigate are SUGGESTIONS: label nothing as fact,
  tie each to the observations that motivate it. Do not write a full promotion strategy.
- evidence_needed: what is missing to judge further (e.g. no evidence about a competitor's channels).
- Never invent numbers, rankings, performance, or competitor activity.
"""

SUGGESTION_INSTRUCTIONS = """
Suggest up to 5 companies or products that plausibly compete with OUR product, based only on the approved
Product Profile. These are UNVERIFIED candidates for the user to check — explain briefly why each might be
relevant. Do not include our own product or the competitors already listed. Do not invent websites; leave
`website_url` null unless you are certain of the official domain.
"""


def _build_graph(schema: Type[BaseModel], title: str, instructions: str, ground: Callable[[CompetitorState, dict], dict]):
    async def generate(state: CompetitorState) -> Dict[str, Any]:
        if state.get("error") and state.get("retries", 0) >= MAX_RETRIES:
            return {}
        prompt = build_stage_prompt(title, state.get("prompt_context") or [], instructions + retry_feedback(state))
        try:
            result = await call_structured(get_provider(), prompt, schema, state, STAGE)
            return {"output": result.model_dump(), "error": None}
        except Exception as e:
            return generation_failure(state, f"Failed to generate {title.lower()}", e)

    def validate(state: CompetitorState) -> Dict[str, Any]:
        if state.get("error"):
            return {}
        return {"output": ground(state, state.get("output") or {})}

    def route(state: CompetitorState) -> str:
        if state.get("error"):
            return "generate" if state.get("retries", 0) < MAX_RETRIES else END
        return "validate"

    builder = StateGraph(CompetitorState)
    builder.add_node("generate", generate)
    builder.add_node("validate", validate)
    builder.add_edge(START, "generate")
    builder.add_conditional_edges("generate", route, {"generate": "generate", "validate": "validate", END: END})
    builder.add_edge("validate", END)
    return builder.compile()


async def _run(graph, state: dict, label: str) -> dict:
    final = await graph.ainvoke({**state, "error": None, "retries": 0})
    if final.get("error"):
        raise RuntimeError(f"{label}: {final['error']}")
    return final.get("output") or {}


_graphs: Dict[str, Any] = {}


def _graph(name: str, factory: Callable[[], Any]):
    if name not in _graphs:
        _graphs[name] = factory()
    return _graphs[name]


async def run_competitor_analysis(state: dict) -> dict:
    from ..competitor_grounding import ground_analysis

    graph = _graph("analysis", lambda: _build_graph(
        CompetitorAnalysisOutput, "Competitor Analysis", ANALYSIS_INSTRUCTIONS,
        lambda s, out: ground_analysis(out, s.get("allowed_refs") or [], s.get("corpus") or "", s.get("evidence_count", 0)),
    ))
    return await _run(graph, state, "Competitor Analysis AI Error")


async def run_competitor_comparison(state: dict) -> dict:
    from ..competitor_grounding import ground_comparison

    graph = _graph("comparison", lambda: _build_graph(
        ComparisonOutput, "Competitor Comparison", COMPARISON_INSTRUCTIONS,
        lambda s, out: ground_comparison(out, s.get("allowed_refs") or [], s.get("corpus") or ""),
    ))
    return await _run(graph, state, "Competitor Comparison AI Error")


async def run_competitor_suggestions(state: dict) -> dict:
    graph = _graph("suggestions", lambda: _build_graph(
        CompetitorSuggestionsOutput, "Competitor Candidates", SUGGESTION_INSTRUCTIONS, lambda s, out: out,
    ))
    return await _run(graph, state, "Competitor Suggestion AI Error")
