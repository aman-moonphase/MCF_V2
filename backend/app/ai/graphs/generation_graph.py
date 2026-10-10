"""Grounded LinkedIn Social Post generation.

START → generate (configured provider, shared schema) → validate (generation_validation)
      ⇄ regenerate with the validation errors fed back (up to max_attempts(): MAX_RETRIES, or 1 in
        single-attempt mode — settings.AI_SINGLE_ATTEMPT) → END

Context loading, prerequisite checks and persistence live in app/services/generation_service.py.
"""

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

from ..generation_schemas import GenerationState, LinkedInPostOutput
from ..generation_validation import validate_post
from ..nodes.common import call_structured, generation_failure, max_attempts, retry_feedback, validation_failure
from ..platform_policy import platform_policy
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider

STAGE = "generate-content"

INSTRUCTIONS = """
Write ONE LinkedIn post for OUR product, using only the approved context above.
- Build it from the selected content pillar and the strategy's messaging direction; use the product's real
  features, audience, problem and value proposition. Address the audience directly.
- Every factual statement about OUR product goes in `claims` as kind "product_fact" and cites S* (sources) or
  P:<field> (approved profile). Messaging that is not a fact is kind "creative".
- Use competitor insights only to choose what to emphasise. Do not name competitors, do not copy their wording,
  and do not state anything about competitors as fact.
- A POSSIBLE OVERLAP (inferred similarity) is not a unique advantage: never present that feature as something only
  we offer. UNRESOLVED comparisons are unknowns: never say or imply a competitor lacks them. SUGGESTIONS are
  optional angles to evaluate, not proven opportunities.
- Never invent statistics, customer numbers, prices, testimonials, or results. If the context lacks something,
  leave it out and say so in `limitations`.
- `hook` is the opening line (short — it must work before "…see more"). Give exactly three different
  `alternative_hooks`. `body` excludes the hook, CTA and hashtags. At most 5 hashtags.
- No placeholders like [insert …], no emoji walls, no generic filler.
"""


async def generate(state: GenerationState) -> Dict[str, Any]:
    if state.get("error") and state.get("retries", 0) >= max_attempts():
        return {}
    prompt = build_stage_prompt("Generate LinkedIn Post", state.get("prompt_context") or [],
                                INSTRUCTIONS + retry_feedback(state))
    try:
        result = await call_structured(get_provider(), prompt, LinkedInPostOutput, state, STAGE)
        return {"output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate the LinkedIn post", e)


def validate(state: GenerationState) -> Dict[str, Any]:
    if state.get("error"):
        return {}
    report = validate_post(state.get("output") or {}, state.get("allowed_refs") or [], state.get("corpus") or "",
                           state.get("meta") or {}, platform_policy())
    if report["errors"]:
        return {**validation_failure(state, " ".join(report["errors"])), "validation": report}
    return {"output": report["post"], "validation": report}


def _after_generate(state: GenerationState) -> str:
    if state.get("error"):
        return "generate" if state.get("retries", 0) < max_attempts() else END
    return "validate"


def _after_validate(state: GenerationState) -> str:
    return "generate" if state.get("error") and state.get("retries", 0) < max_attempts() else END


def build_generation_graph():
    builder = StateGraph(GenerationState)
    builder.add_node("generate", generate)
    builder.add_node("validate", validate)
    builder.add_edge(START, "generate")
    builder.add_conditional_edges("generate", _after_generate, {"generate": "generate", "validate": "validate", END: END})
    builder.add_conditional_edges("validate", _after_validate, {"generate": "generate", END: END})
    return builder.compile()


_graph = None


async def run_linkedin_generation(state: dict) -> dict:
    """Returns {"post": ..., "validation": ...}. Raises RuntimeError when no valid post could be produced."""
    global _graph
    if _graph is None:
        _graph = build_generation_graph()
    final = await _graph.ainvoke({**state, "error": None, "retries": 0})
    if final.get("error"):
        raise RuntimeError(f"Generation failed: {final['error']}")
    return {"post": final.get("output") or {}, "validation": final.get("validation") or {}}
