"""Scoped access to the current workflow state during a provider call.

Real providers only ever see the prompt. The deterministic DemoProvider is not a language model,
so instead of re-parsing prompt text it reads the same current-project data from this context.
Nodes set it around every provider call (see app/ai/nodes/common.py); it is reset afterwards, so
nothing can leak between requests or projects.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping, Optional

_current_context: ContextVar[Optional[Mapping[str, Any]]] = ContextVar("mcf_generation_context", default=None)


@contextmanager
def generation_context(state: Mapping[str, Any], stage: str) -> Iterator[None]:
    token = _current_context.set({**state, "stage": stage})
    try:
        yield
    finally:
        _current_context.reset(token)


def get_generation_context() -> Optional[Mapping[str, Any]]:
    return _current_context.get()
