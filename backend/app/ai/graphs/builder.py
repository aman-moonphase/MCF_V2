"""One graph shape for every workflow stage:

    START → [analyze] → generate ⇄ (retry on error) → validate ⇄ (regenerate on invalid output) → END

- An analyze error (e.g. missing context) ends the run instead of being masked by generate.
- Generation errors retry up to MAX_RETRIES.
- Validation failures (wrong schema shape, approved content type violated) also regenerate,
  with the rejection reason fed back into the prompt.
"""

from typing import Callable, Optional, Tuple

from langgraph.graph import END, START, StateGraph

from ..nodes.common import MAX_RETRIES
from ..schemas import AIState

Node = Tuple[str, Callable]


def make_should_retry(generate_name: str, validate_name: str) -> Callable[[AIState], str]:
    def should_retry(state: AIState) -> str:
        if state.get("error"):
            if state.get("retries", 0) < MAX_RETRIES:
                return generate_name
            return END
        return validate_name

    return should_retry


def build_stage_graph(analyze: Optional[Node], generate: Node, validate: Node, should_retry: Callable[[AIState], str]):
    generate_name, validate_name = generate[0], validate[0]

    builder = StateGraph(AIState)
    builder.add_node(*generate)
    builder.add_node(*validate)

    if analyze:
        analyze_name = analyze[0]
        builder.add_node(*analyze)
        builder.add_edge(START, analyze_name)
        builder.add_conditional_edges(
            analyze_name,
            lambda state: END if state.get("error") else generate_name,
            {generate_name: generate_name, END: END},
        )
    else:
        builder.add_edge(START, generate_name)

    builder.add_conditional_edges(
        generate_name,
        should_retry,
        {generate_name: generate_name, validate_name: validate_name, END: END},
    )

    def after_validate(state: AIState) -> str:
        if state.get("error") and state.get("retries", 0) < MAX_RETRIES:
            return generate_name
        return END

    builder.add_conditional_edges(validate_name, after_validate, {generate_name: generate_name, END: END})

    return builder.compile()
