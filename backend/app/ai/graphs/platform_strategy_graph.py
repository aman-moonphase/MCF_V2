from .builder import build_stage_graph, make_should_retry
from ..nodes.platform_strategy_nodes import analyze_content, generate_platforms, validate_result

should_retry = make_should_retry("generate_platforms", "validate_result")


def build_platform_strategy_graph():
    return build_stage_graph(
        analyze=("analyze_content", analyze_content),
        generate=("generate_platforms", generate_platforms),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
