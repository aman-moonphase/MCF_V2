from typing import Any, Dict

from ..content_types import check_platform_recommendations, constraint_block
from ..prompts import build_stage_prompt
from ..providers.factory import get_configured_provider as get_provider
from ..schemas import AIState, PlatformStrategyOutput
from .common import call_structured, call_text, generation_failure, retry_feedback, validation_failure
from .common_context import opportunity_context, source_context

STAGE = "platform-strategy"


async def analyze_content(state: AIState) -> Dict[str, Any]:
    """Analyze the original source and the selected opportunity."""
    input_text = state.get("input_text", "")
    selected_opportunity = state.get("selected_opportunity", {})

    if not input_text or not selected_opportunity:
        return {"error": "Missing input text or selected opportunity"}

    provider = get_provider()

    prompt = build_stage_prompt(
        "Platform Analysis",
        [*source_context(state), *opportunity_context(selected_opportunity)],
        "Extract the core themes and the target audience of the selected opportunity to prepare "
        "platform strategy recommendations.",
    )

    try:
        analysis = await call_text(provider, prompt, state, STAGE)
        return {"intent": analysis}
    except Exception as e:
        return {"error": f"Failed to analyze content: {str(e)}"}


async def generate_platforms(state: AIState) -> Dict[str, Any]:
    """Generate platform recommendations based on the analysis."""
    if state.get("error") and state.get("retries", 0) >= 3:
        return {}  # Max retries reached

    provider = get_provider()
    approved_type = state.get("approved_content_type")

    prompt = build_stage_prompt(
        "Platform Strategy",
        [
            *source_context(state),
            *opportunity_context(state.get("selected_opportunity")),
            ("Analysis", state.get("intent")),
        ],
        f"""
{constraint_block(approved_type)}

Recommend 2-4 platforms where this exact deliverable can be published.
Only recommend platforms that natively support the approved content type, and make every
`recommendedFormat` a version of that content type on that platform.

For each platform recommendation, provide:
- A unique ID (e.g. 'plat-1')
- projectId: use the string 'project'
- The platform name (e.g. LinkedIn, Instagram, YouTube, X (Twitter), Blog, Email)
- A suitability score from 0 to 100
- Reasoning for why it is a good fit for this project's audience
- The recommended format
- The recommended length
- The target audience on this platform
- The tone
- The priority ('Recommended' or 'Optional')
{retry_feedback(state)}
""",
    )

    try:
        result = await call_structured(provider, prompt, PlatformStrategyOutput, state, STAGE)
        return {"structured_output": result.model_dump(), "error": None}
    except Exception as e:
        return generation_failure(state, "Failed to generate platform recommendations", e)


async def validate_result(state: AIState) -> Dict[str, Any]:
    """Validate the final output."""
    if state.get("error"):
        return state

    output = state.get("structured_output")
    if not output or "recommendations" not in output:
        return validation_failure(state, "Missing recommendations in generated output")

    if not isinstance(output["recommendations"], list) or len(output["recommendations"]) == 0:
        return validation_failure(state, "Generated recommendations list is empty or invalid")

    violation = check_platform_recommendations(state.get("approved_content_type"), output["recommendations"])
    if violation:
        return validation_failure(state, violation)

    return state
