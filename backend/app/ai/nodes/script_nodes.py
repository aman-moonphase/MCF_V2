from typing import Any, Dict

from ..content_types import check_script, constraint_block, get_profile
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, ScriptOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import angle_context, source_context, strategy_context

STAGE = "final-script"


def _scenes_detail(scenes: list) -> str:
    return "\n".join(
        f"Scene {s.get('order')}: {s.get('title')} | Purpose: {s.get('purpose')} | "
        f"Narration: {s.get('narration')} | Visual: {s.get('visualDirection')} | "
        f"On-Screen: {s.get('onScreenText')} | Duration: {s.get('estimatedDuration')}"
        for s in scenes
    )


async def analyze_storyboard_context(state: AIState) -> Dict[str, Any]:
    """
    Analyze the approved storyboard and full workflow context to prepare
    for script generation. Identifies per-scene narrative expansion strategy.
    """
    input_text = state.get("input_text", "")
    selected_opportunity = state.get("selected_opportunity", {})
    selected_platforms = state.get("selected_platforms", [])
    selected_angle = state.get("selected_angle", {})
    approved_strategy = state.get("approved_strategy", {})
    approved_storyboard = state.get("approved_storyboard", {})

    if (
        not input_text
        or not selected_opportunity
        or not selected_platforms
        or not selected_angle
        or not approved_strategy
        or not approved_storyboard
    ):
        return {"error": "Missing required context for script generation"}

    scenes = approved_storyboard.get("scenes", [])
    if not scenes:
        return {"error": "Approved storyboard has no scenes — cannot generate script"}

    provider = get_provider()

    platform_name = selected_platforms[0].get("platform", "Unknown") if selected_platforms else "Unknown"
    platform_format = selected_platforms[0].get("recommendedFormat", "") if selected_platforms else ""

    prompt = build_stage_prompt(
        "Final Script Analysis",
        [
            ("Source Topic", input_text),
            ("Approved Content Type", state.get("approved_content_type")),
            ("Platform", f"{platform_name} ({platform_format})" if platform_format else platform_name),
            ("Tone", approved_strategy.get("tone")),
            ("Hook Strategy", approved_strategy.get("hookStrategy")),
            ("Call to Action", approved_strategy.get("callToAction")),
            (f"Approved Storyboard — {len(scenes)} units", ", ".join(s.get("title", "") for s in scenes)),
        ],
        "For each storyboard unit, identify what copy expansion and platform adaptation is needed "
        "to turn the storyboard into a final, publish-ready script.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze storyboard context: {str(e)}"}


async def generate_script(state: AIState) -> Dict[str, Any]:
    """
    Generate the final script by expanding each storyboard scene into a
    complete, platform-adapted script section.
    """
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached — abort

    provider = get_provider()
    approved_type = state.get("approved_content_type")
    profile = get_profile(approved_type)
    unit = profile.unit if profile else "scene"

    selected_platforms = state.get("selected_platforms") or []
    approved_strategy = state.get("approved_strategy") or {}
    approved_storyboard = state.get("approved_storyboard") or {}
    platform_name = selected_platforms[0].get("platform", "Unknown") if selected_platforms else "Unknown"
    platform_format = selected_platforms[0].get("recommendedFormat", "") if selected_platforms else ""

    prompt = build_stage_prompt(
        "Final Script",
        [
            *source_context(state),
            ("Platform", platform_name),
            ("Platform Format", platform_format),
            *strategy_context(approved_strategy),
            *angle_context(state.get("selected_angle")),
            ("Approved Storyboard (MUST be followed in order)", _scenes_detail(approved_storyboard.get("scenes", []))),
            ("Analysis", state.get("intent")),
        ],
        f"""
{constraint_block(approved_type)}

Generate the final, publish-ready script for this {approved_type or 'content'}. It MUST follow the approved
storyboard exactly — one ScriptSection per storyboard {unit}, in the same order, preserving the
narrative beats and visual direction. Each section's narration is the polished, platform-adapted copy.
The script `format` field must describe the approved content type. Adapt the tone for {platform_name}.
Set `status` to 'Draft'.
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, ScriptOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate script", e)


async def validate_script_result(state: AIState) -> Dict[str, Any]:
    """Validate that the generated script has the required structure."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "script" not in output:
        return validation_failure(state, "Missing 'script' key in generated output")

    script = output["script"]
    if not isinstance(script.get("sections"), list) or len(script["sections"]) == 0:
        return validation_failure(state, "Generated script has no sections")

    violation = check_script(state.get("approved_content_type"), script)
    if violation:
        return validation_failure(state, violation)

    return state
