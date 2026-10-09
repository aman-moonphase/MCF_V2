from typing import Any, Type

from pydantic import BaseModel

from .base import AIProviderError, BaseAIProvider
from ..prompts import PROVIDER_SYSTEM_PROMPT

PROVIDER_NAME = "claude"


class ClaudeProvider(BaseAIProvider):
    """Claude via the official Anthropic SDK.

    Structured output uses `messages.parse(output_format=<PydanticModel>)`, so responses are
    validated against the same Pydantic schemas the LangGraph nodes already use.
    """

    def __init__(
        self,
        api_key: str,
        model_name: str = "claude-opus-5-5",
        max_tokens: int = 16000,
        effort: str | None = "medium",
        timeout: float = 120.0,
        client: Any = None,
    ):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is required when using the 'claude' provider.")
        if client is None:
            import anthropic

            # The SDK itself retries 408/409/429/5xx and connection errors (max_retries).
            client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout, max_retries=2)
        self.client = client
        self.model_name = model_name
        self.max_tokens = max_tokens
        self.effort = effort

    def _request_kwargs(self, prompt: str) -> dict:
        kwargs: dict = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "system": PROVIDER_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        }
        if self.effort:
            kwargs["output_config"] = {"effort": self.effort}
        return kwargs

    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any:
        kwargs = self._request_kwargs(prompt)
        response = await self._call(self.client.messages.parse, output_format=schema, **kwargs)
        self._check_stop_reason(response)
        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            raise AIProviderError(
                f"Claude returned no parsable {schema.__name__} output.",
                provider=PROVIDER_NAME,
                retryable=True,
            )
        return parsed

    async def generate_text(self, prompt: str) -> str:
        response = await self._call(self.client.messages.create, **self._request_kwargs(prompt))
        self._check_stop_reason(response)
        text = "".join(block.text for block in response.content if getattr(block, "type", None) == "text")
        if not text.strip():
            raise AIProviderError("Claude returned an empty text response.", provider=PROVIDER_NAME, retryable=True)
        return text

    async def _call(self, method, **kwargs):
        import anthropic

        try:
            return await method(**kwargs)
        except anthropic.AuthenticationError as e:
            raise AIProviderError(
                "Claude authentication failed. Check ANTHROPIC_API_KEY.", provider=PROVIDER_NAME
            ) from e
        except anthropic.PermissionDeniedError as e:
            raise AIProviderError(
                "The Anthropic API key does not have permission for this request.", provider=PROVIDER_NAME
            ) from e
        except anthropic.NotFoundError as e:
            raise AIProviderError(
                f"Claude model '{self.model_name}' was not found. Check CLAUDE_MODEL.", provider=PROVIDER_NAME
            ) from e
        except anthropic.BadRequestError as e:
            raise AIProviderError(f"Claude rejected the request: {e.message}", provider=PROVIDER_NAME) from e
        except anthropic.RateLimitError as e:
            raise AIProviderError(
                "Claude rate limit reached. Try again shortly.", provider=PROVIDER_NAME, retryable=True
            ) from e
        except anthropic.APIStatusError as e:
            raise AIProviderError(
                f"Claude API error ({e.status_code}).", provider=PROVIDER_NAME, retryable=e.status_code >= 500
            ) from e
        except anthropic.APITimeoutError as e:
            raise AIProviderError("Claude request timed out.", provider=PROVIDER_NAME, retryable=True) from e
        except anthropic.APIConnectionError as e:
            raise AIProviderError("Could not reach the Claude API.", provider=PROVIDER_NAME, retryable=True) from e

    @staticmethod
    def _check_stop_reason(response) -> None:
        stop_reason = getattr(response, "stop_reason", None)
        if stop_reason == "refusal":
            raise AIProviderError("Claude declined to generate this content.", provider=PROVIDER_NAME)
        if stop_reason == "max_tokens":
            raise AIProviderError(
                "Claude output was cut off at CLAUDE_MAX_TOKENS before it was complete.",
                provider=PROVIDER_NAME,
            )
