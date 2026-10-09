from .builder import build_stage_graph, make_should_retry
from ..nodes.storyboard_nodes import analyze_context, generate_storyboard, validate_result

should_retry = make_should_retry("generate_storyboard", "validate_result")


def build_storyboard_graph():
    return build_stage_graph(
        analyze=("analyze_context", analyze_context),
        generate=("generate_storyboard", generate_storyboard),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
