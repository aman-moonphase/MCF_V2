from .builder import build_stage_graph, make_should_retry
from ..nodes.content_strategy_nodes import analyze_context, generate_strategy, validate_result

should_retry = make_should_retry("generate_strategy", "validate_result")


def build_content_strategy_graph():
    return build_stage_graph(
        analyze=("analyze_context", analyze_context),
        generate=("generate_strategy", generate_strategy),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
