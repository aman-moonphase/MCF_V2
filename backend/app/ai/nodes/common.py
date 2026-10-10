"""Helpers shared by every workflow stage node."""

from typing import Any, Dict, Type

from pydantic import BaseModel

from ..generation_context import generation_context
from ..providers.base import AIProviderError, BaseAIProvider
from ..schemas import AIState

MAX_RETRIES = 3
SDK_MAX_RETRIES = 2  # Anthropic SDK retries for 408/409/429/5xx and connection errors (normal mode)


def max_attempts() -> int:
    """Generation attempts per AI step: 1 in single-attempt mode (settings.AI_SINGLE_ATTEMPT), else MAX_RETRIES."""
    from ...core.config import settings

    return 1 if settings.AI_SINGLE_ATTEMPT else MAX_RETRIES


def sdk_max_retries() -> int:
    """SDK-level retries per request: 0 in single-attempt mode, else SDK_MAX_RETRIES."""
    from ...core.config import settings

    return 0 if settings.AI_SINGLE_ATTEMPT else SDK_MAX_RETRIES


async def call_structured(provider: BaseAIProvider, prompt: str, schema: Type[BaseModel], state: AIState, stage: str) -> Any:
    with generation_context(state, stage):
        return await provider.generate_structured(prompt, schema)


async def call_text(provider: BaseAIProvider, prompt: str, state: AIState, stage: str) -> str:
    with generation_context(state, stage):
        return await provider.generate_text(prompt)


def generation_failure(state: AIState, message: str, exc: Exception) -> Dict[str, Any]:
    """State update for a failed generate call. Non-retryable provider errors stop the retry loop."""
    retries = state.get("retries", 0) + 1
    if isinstance(exc, AIProviderError) and not exc.retryable:
        retries = max(retries, max_attempts())
    return {"error": f"{message}: {exc}", "retries": retries}


def validation_failure(state: AIState, message: str) -> Dict[str, Any]:
    """State update for output that failed validation; the graph routes back to regenerate."""
    return {"error": message, "retries": state.get("retries", 0) + 1}


def retry_feedback(state: AIState) -> str:
    """Tell the model why the previous attempt was rejected, so a retry can correct it."""
    error = state.get("error")
    if error and state.get("retries", 0) > 0:
        return f"\nPREVIOUS ATTEMPT WAS REJECTED: {error}\nCorrect this in the new output.\n"
    return ""


def grounding_text(state: AIState) -> str:
    grounding = state.get("grounding_context") or {}
    return grounding.get("text", "") if isinstance(grounding, dict) else ""
