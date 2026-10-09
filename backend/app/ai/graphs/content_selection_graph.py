from .builder import build_stage_graph, make_should_retry
from ..nodes.content_selection_nodes import analyze_source, generate_recommendations, validate_result

should_retry = make_should_retry("generate_recommendations", "validate_result")


def build_content_selection_graph():
    return build_stage_graph(
        analyze=("analyze_source", analyze_source),
        generate=("generate_recommendations", generate_recommendations),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
