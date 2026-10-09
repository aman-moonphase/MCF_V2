from .builder import build_stage_graph, make_should_retry
from ..nodes.script_nodes import analyze_storyboard_context, generate_script, validate_script_result

should_retry = make_should_retry("generate_script", "validate_script_result")


def build_script_graph():
    return build_stage_graph(
        analyze=("analyze_storyboard_context", analyze_storyboard_context),
        generate=("generate_script", generate_script),
        validate=("validate_script_result", validate_script_result),
        should_retry=should_retry,
    )
