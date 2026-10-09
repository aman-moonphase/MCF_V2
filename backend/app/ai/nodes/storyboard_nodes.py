from typing import Any, Dict

from ..content_types import check_storyboard, constraint_block, get_profile
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, StoryboardOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import angle_context, platforms_context, source_context, strategy_context

STAGE = "storyboard"


async def analyze_context(state: AIState) -> Dict[str, Any]:
    """Analyze the overall context including original source, opportunity, platforms, angle, and strategy."""
    input_text = state.get("input_text", "")
    selected_opportunity = state.get("selected_opportunity", {})
    selected_platforms = state.get("selected_platforms", [])
    selected_angle = state.get("selected_angle", {})
    approved_strategy = state.get("approved_strategy", {})

    if not input_text or not selected_opportunity or not selected_platforms or not selected_angle or not approved_strategy:
        return {"error": "Missing required context for storyboard"}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Storyboard Analysis",
        [
            ("Approved Content Type", state.get("approved_content_type")),
            *strategy_context(approved_strategy),
            *angle_context(selected_angle),
        ],
        "Identify the key narrative beats required to translate this strategy into an ordered storyboard.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze context: {str(e)}"}


async def generate_storyboard(state: AIState) -> Dict[str, Any]:
    """Generate the full storyboard based on the analyzed context."""
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached

    provider = get_provider()
    approved_type = state.get("approved_content_type")
    profile = get_profile(approved_type)
    unit = profile.unit if profile else "scene"

    approved_strategy = state.get("approved_strategy") or {}
    platforms = approved_strategy.get("platformAdaptations") or state.get("selected_platforms") or []

    prompt = build_stage_prompt(
        "Storyboard",
        [
            *source_context(state),
            *strategy_context(approved_strategy),
            *angle_context(state.get("selected_angle")),
            *platforms_context(platforms),
            ("Analysis", state.get("intent")),
        ],
        f"""
{constraint_block(approved_type)}

Generate an ordered storyboard of {unit}s that brings the approved strategy to life.
Each {unit} must have a purpose, narration/copy, visual direction, on-screen text, a transition,
and an estimated duration (use 'N/A' or a read time where duration does not apply).
The storyboard must be logically derived from the strategy and stay about this project's subject.
For ids use '{unit}-1', '{unit}-2', ...; set `projectId` to 'project' and `status` to 'Draft'.
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, StoryboardOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate storyboard", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    """Validate the final output."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "storyboard" not in output:
        return validation_failure(state, "Missing storyboard in generated output")

    violation = check_storyboard(state.get("approved_content_type"), output["storyboard"] or {})
    if violation:
        return validation_failure(state, violation)

    return state
