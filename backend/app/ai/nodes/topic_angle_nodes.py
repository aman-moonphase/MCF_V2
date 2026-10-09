from typing import Any, Dict

from ..content_types import check_topic_angles, constraint_block
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, TopicAngleOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import opportunity_context, platforms_context, source_context

STAGE = "topic-angle"


async def analyze_context(state: AIState) -> Dict[str, Any]:
    """Analyze the overall context including original source, selected opportunity, and selected platforms."""
    input_text = state.get("input_text", "")
    selected_opportunity = state.get("selected_opportunity", {})
    selected_platforms = state.get("selected_platforms", [])

    if not input_text or not selected_opportunity or not selected_platforms:
        return {"error": "Missing required context (input text, selected opportunity, or selected platforms)"}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Topic & Angle Analysis",
        [*source_context(state), *opportunity_context(selected_opportunity), *platforms_context(selected_platforms)],
        "Identify the core messages from this project that will resonate with this audience on these platforms.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze context: {str(e)}"}


async def generate_angles(state: AIState) -> Dict[str, Any]:
    """Generate topic angles based on the analyzed context."""
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached

    provider = get_provider()
    approved_type = state.get("approved_content_type")

    prompt = build_stage_prompt(
        "Topic & Angle",
        [
            *source_context(state),
            *opportunity_context(state.get("selected_opportunity")),
            *platforms_context(state.get("selected_platforms")),
            ("Analysis", state.get("intent")),
        ],
        f"""
{constraint_block(approved_type)}

Generate 3-4 distinct topic angles (e.g. Contrarian, Educational, Blueprint, Story-driven) for this
project's subject. The `angle` field names the perspective, not a different deliverable format.

For each angle, provide:
- A unique ID (e.g. 'ang-1')
- projectId: use the string 'project'
- A working title
- The specific angle (e.g. 'Contrarian', 'Educational')
- An opening hook
- A brief description
- The target audience
- The core promise or takeaway
- How it differentiates from generic content
- 3-5 supporting points drawn from the source
- The platforms from the selected list that this angle suits best
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, TopicAngleOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate topic angles", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    """Validate the final output."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "angles" not in output:
        return validation_failure(state, "Missing angles in generated output")

    if not isinstance(output["angles"], list) or len(output["angles"]) == 0:
        return validation_failure(state, "Generated angles list is empty or invalid")

    violation = check_topic_angles(state.get("approved_content_type"), output["angles"])
    if violation:
        return validation_failure(state, violation)

    return state
