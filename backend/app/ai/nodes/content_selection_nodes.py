from typing import Any, Dict

from ..content_types import check_opportunities, constraint_block
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, ContentSelectionOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import source_context

STAGE = "content-selection"


async def analyze_source(state: AIState) -> Dict[str, Any]:
    """Analyze the input text to extract key themes and potential audiences."""
    input_text = state.get("input_text", "")

    if not input_text:
        return {"error": "Input text is empty"}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Source Analysis",
        source_context(state),
        "Analyze the source material. Identify the main themes, the potential target audiences, "
        "and the core value proposition. Use only what the source supports.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze source: {str(e)}"}


async def generate_recommendations(state: AIState) -> Dict[str, Any]:
    """Generate content opportunities based on the input text and analysis."""
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached

    provider = get_provider()
    approved_type = state.get("approved_content_type")

    if approved_type:
        type_rule = (
            f"Generate 3-5 distinct content opportunities that are ALL \"{approved_type}\" deliverables. "
            f"EVERY opportunity must set its `content_type` field exactly to \"{approved_type}\". "
            "Keep the `platform` (e.g. LinkedIn, YouTube, Instagram) separate from the `content_type`."
        )
    else:
        type_rule = (
            "Recommend 3-5 distinct content opportunities that would be valuable for the target audience. "
            "Set the `content_type` field accurately for each."
        )

    prompt = build_stage_prompt(
        "Content Selection",
        [*source_context(state), ("Source Analysis", state.get("intent"))],
        f"""
{constraint_block(approved_type)}

{type_rule}

For each opportunity, provide:
- A unique ID (e.g. 'opt-1')
- The `content_type`
- The target `platform`
- A specific title about this project's subject
- A brief summary
- Why it is interesting or valuable to the audience
- 3-5 key points it will cover, drawn from the source
- The specific potential audience
- The estimated value or impact
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, ContentSelectionOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate recommendations", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    """Validate the final output."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "opportunities" not in output:
        return validation_failure(state, "Missing opportunities in generated output")

    if not isinstance(output["opportunities"], list) or len(output["opportunities"]) == 0:
        return validation_failure(state, "Generated opportunities list is empty or invalid")

    violation = check_opportunities(state.get("approved_content_type"), output["opportunities"])
    if violation:
        return validation_failure(state, violation)

    return state
