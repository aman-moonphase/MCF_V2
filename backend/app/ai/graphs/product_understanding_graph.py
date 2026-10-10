"""START → analyze_sources → build_profile → identify_gaps → generate_questions → validate → END

Errors end the run (analyze) or retry the failing structured step up to MAX_RETRIES.
"""

from langgraph.graph import END, START, StateGraph

from ..nodes.common import max_attempts
from ..nodes.product_understanding_nodes import (
    analyze_sources, build_profile, generate_questions, identify_gaps, validate_understanding,
)
from ..product_schemas import ProductUnderstandingState


def _retry_or(next_node: str, same_node: str):
    def route(state: ProductUnderstandingState) -> str:
        if state.get("error"):
            return same_node if state.get("retries", 0) < max_attempts() else END
        return next_node
    return route


def build_product_understanding_graph():
    builder = StateGraph(ProductUnderstandingState)
    builder.add_node("analyze_sources", analyze_sources)
    builder.add_node("build_profile", build_profile)
    builder.add_node("identify_gaps", identify_gaps)
    builder.add_node("generate_questions", generate_questions)
    builder.add_node("validate_understanding", validate_understanding)

    builder.add_edge(START, "analyze_sources")
    builder.add_conditional_edges(
        "analyze_sources", lambda s: END if s.get("error") else "build_profile", {"build_profile": "build_profile", END: END}
    )
    builder.add_conditional_edges(
        "build_profile", _retry_or("identify_gaps", "build_profile"),
        {"identify_gaps": "identify_gaps", "build_profile": "build_profile", END: END},
    )
    builder.add_edge("identify_gaps", "generate_questions")
    builder.add_conditional_edges(
        "generate_questions", _retry_or("validate_understanding", "generate_questions"),
        {"validate_understanding": "validate_understanding", "generate_questions": "generate_questions", END: END},
    )
    builder.add_edge("validate_understanding", END)
    return builder.compile()


_graph = None


async def run_product_understanding(
    input_text: str,
    grounding_context: dict | None = None,
    current_profile: dict | None = None,
    clarifications: list | None = None,
    asked_fields: list | None = None,
    edited_fields: list | None = None,
) -> dict:
    """Returns {profile, missing_fields, questions}. Raises RuntimeError on failure."""
    global _graph
    if _graph is None:
        _graph = build_product_understanding_graph()
    final = await _graph.ainvoke({
        "input_text": input_text,
        "grounding_context": grounding_context or {},
        "current_profile": current_profile,
        "clarifications": clarifications or [],
        "asked_fields": asked_fields or [],
        "edited_fields": edited_fields or [],
        "intent": None,
        "error": None,
        "retries": 0,
    })
    if final.get("error"):
        raise RuntimeError(f"Product Understanding AI Error: {final['error']}")
    return {
        "profile": final.get("profile") or {},
        "missing_fields": final.get("missing_fields") or [],
        "questions": final.get("questions") or [],
    }
