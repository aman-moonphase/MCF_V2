from .builder import build_stage_graph, make_should_retry
from ..nodes.content_type_nodes import recommend_type, validate_result

should_retry = make_should_retry("recommend_type", "validate_result")


def build_content_type_graph():
    return build_stage_graph(
        analyze=None,
        generate=("recommend_type", recommend_type),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
