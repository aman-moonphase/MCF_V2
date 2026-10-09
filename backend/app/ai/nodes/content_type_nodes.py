from typing import Any, Dict

from ..content_types import CONTENT_TYPES
from ..prompts import bullet_list, build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, ContentTypeOutput
from .common import call_structured, generation_failure, retry_feedback, validation_failure
from .common_context import source_context

STAGE = "content-type"


async def recommend_type(state: AIState) -> Dict[str, Any]:
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Content Type Recommendation",
        source_context(state),
        f"""
Recommend the single most suitable primary content type for this project, plus a few alternatives.
You MUST choose ONLY from these exact six options (no other names or variations):
{bullet_list(CONTENT_TYPES)}

Base the reasoning on signals that are actually present in the source material, and list those signals.
{retry_feedback(state)}
""",
    )

    try:
        result: ContentTypeOutput = await call_structured(provider, prompt, ContentTypeOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to recommend content type", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output:
        return validation_failure(state, "No output generated")

    try:
        ContentTypeOutput(**output)
        return state
    except Exception as e:
        return validation_failure(state, f"Validation failed: {str(e)}")
