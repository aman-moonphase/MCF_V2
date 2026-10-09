from typing import Any, Dict

from ..content_types import check_strategy, constraint_block
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, ContentStrategyOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import angle_context, opportunity_context, platforms_context, source_context

STAGE = "content-strategy"


async def analyze_context(state: AIState) -> Dict[str, Any]:
    """Analyze the overall context including original source, opportunity, platforms, and topic angle."""
    input_text = state.get("input_text", "")
    selected_opportunity = state.get("selected_opportunity", {})
    selected_platforms = state.get("selected_platforms", [])
    selected_angle = state.get("selected_angle", {})

    if not input_text or not selected_opportunity or not selected_platforms or not selected_angle:
        return {"error": "Missing required context for content strategy"}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Content Strategy Analysis",
        [
            *source_context(state),
            *opportunity_context(selected_opportunity),
            *platforms_context(selected_platforms),
            *angle_context(selected_angle),
        ],
        "Identify the overarching objective and narrative structure that ties these elements together.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze context: {str(e)}"}


async def generate_strategy(state: AIState) -> Dict[str, Any]:
    """Generate the full content strategy based on the analyzed context."""
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached

    provider = get_provider()
    approved_type = state.get("approved_content_type")

    prompt = build_stage_prompt(
        "Content Strategy",
        [
            *source_context(state),
            *opportunity_context(state.get("selected_opportunity")),
            *platforms_context(state.get("selected_platforms")),
            *angle_context(state.get("selected_angle")),
            ("Analysis", state.get("intent")),
        ],
        f"""
{constraint_block(approved_type)}

Produce a complete content strategy that acts as the blueprint for this one {approved_type or 'piece of content'}.
The `format` field and every platform adaptation's `format` must describe the approved content type.
Include specific platform adaptations for the selected platforms.
For `id` use 'strategy-1' and for `projectId` use the string 'project'.
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, ContentStrategyOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate content strategy", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    """Validate the final output."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "strategy" not in output:
        return validation_failure(state, "Missing strategy in generated output")

    violation = check_strategy(state.get("approved_content_type"), output["strategy"] or {})
    if violation:
        return validation_failure(state, violation)

    return state
