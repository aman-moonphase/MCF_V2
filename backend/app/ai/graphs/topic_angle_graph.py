from .builder import build_stage_graph, make_should_retry
from ..nodes.topic_angle_nodes import analyze_context, generate_angles, validate_result

should_retry = make_should_retry("generate_angles", "validate_result")


def build_topic_angle_graph():
    return build_stage_graph(
        analyze=("analyze_context", analyze_context),
        generate=("generate_angles", generate_angles),
        validate=("validate_result", validate_result),
        should_retry=should_retry,
    )
