from abc import ABC, abstractmethod
from typing import Any, Type
from pydantic import BaseModel


class AIProviderError(Exception):
    """A provider call failed in a way the workflow should report cleanly.

    `retryable` tells the LangGraph retry loop whether repeating the same request can help
    (rate limits, timeouts, 5xx) or not (bad credentials, invalid request, refusal).
    """

    def __init__(self, message: str, *, provider: str, retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class BaseAIProvider(ABC):
    @abstractmethod
    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any:
        """Generate structured output matching the provided Pydantic schema."""
        pass

    @abstractmethod
    async def generate_text(self, prompt: str) -> str:
        """Generate plain text output."""
        pass
