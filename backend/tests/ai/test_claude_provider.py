"""Claude provider: factory wiring, request shape, structured output, and error handling.

All tests use a fake Anthropic client — no network calls and no API key are needed.
"""
from types import SimpleNamespace
from unittest.mock import patch

import anthropic
import httpx2
import pytest

from app.ai.config import AIConfig, build_ai_config
from app.ai.nodes.common import MAX_RETRIES, generation_failure
from app.ai.prompts import PROVIDER_SYSTEM_PROMPT
from app.ai.providers.base import AIProviderError
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.demo_provider import DemoProvider
from app.ai.providers.factory import AIProviderFactory
from app.ai.schemas import ContentSelectionOutput, ContentTypeOutput

CONTENT_TYPE_RESULT = ContentTypeOutput(
    recommendation={
        "recommendedType": "Carousel",
        "alternatives": ["Article"],
        "reasoning": "The source lists several features.",
        "sourceSignals": ["feature list"],
    }
)


class FakeMessages:
    def __init__(self, parse_response=None, create_response=None, error=None):
        self.parse_response = parse_response
        self.create_response = create_response
        self.error = error
        self.calls = []

    async def parse(self, **kwargs):
        self.calls.append(("parse", kwargs))
        if self.error:
            raise self.error
        return self.parse_response

    async def create(self, **kwargs):
        self.calls.append(("create", kwargs))
        if self.error:
            raise self.error
        return self.create_response


def make_provider(**fake_kwargs) -> tuple[ClaudeProvider, FakeMessages]:
    messages = FakeMessages(**fake_kwargs)
    provider = ClaudeProvider(
        api_key="test-key", model_name="claude-opus-5-5", max_tokens=1234, effort="medium",
        client=SimpleNamespace(messages=messages),
    )
    return provider, messages


def _response(status: int) -> httpx2.Response:
    return httpx2.Response(status, request=httpx2.Request("POST", "https://api.anthropic.com/v1/messages"))


# ─── Factory / configuration ─────────────────────────────────────────────────

def test_factory_returns_claude_provider_with_key():
    provider = AIProviderFactory.get_provider(AIConfig(provider="claude", api_key="sk-test", model_name="claude-opus-5-5"))
    assert isinstance(provider, ClaudeProvider)


def test_factory_accepts_anthropic_alias():
    provider = AIProviderFactory.get_provider(AIConfig(provider="Anthropic", api_key="sk-test"))
    assert isinstance(provider, ClaudeProvider)


def test_factory_requires_anthropic_key():
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        AIProviderFactory.get_provider(AIConfig(provider="claude", api_key=None))


def test_factory_has_no_silent_fallback_for_unknown_provider():
    with pytest.raises(ValueError, match="Unsupported AI_PROVIDER"):
        AIProviderFactory.get_provider(AIConfig(provider="gemini"))


def test_demo_still_works_without_any_key():
    assert isinstance(AIProviderFactory.get_provider(AIConfig(provider="demo")), DemoProvider)


def test_build_ai_config_reads_claude_settings_from_environment():
    with patch("app.core.config.settings.AI_PROVIDER", "claude"), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", "sk-from-env"), \
         patch("app.core.config.settings.CLAUDE_MODEL", "claude-sonnet-5-5"), \
         patch("app.core.config.settings.CLAUDE_EFFORT", "high"):
        config = build_ai_config()
    assert config.provider == "claude"
    assert config.api_key == "sk-from-env"
    assert config.model_name == "claude-sonnet-5-5"
    assert config.effort == "high"


def test_build_ai_config_does_not_mix_provider_keys():
    with patch("app.core.config.settings.AI_PROVIDER", "openai"), \
         patch("app.core.config.settings.OPENAI_API_KEY", "openai-key"), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", "anthropic-key"):
        config = build_ai_config()
    assert config.api_key == "openai-key"


# ─── Request shape / structured output ───────────────────────────────────────

@pytest.mark.asyncio
async def test_generate_structured_uses_parse_with_pydantic_schema():
    provider, messages = make_provider(
        parse_response=SimpleNamespace(stop_reason="end_turn", parsed_output=CONTENT_TYPE_RESULT)
    )
    result = await provider.generate_structured("PROMPT TEXT", ContentTypeOutput)

    assert result is CONTENT_TYPE_RESULT
    method, kwargs = messages.calls[0]
    assert method == "parse"
    assert kwargs["output_format"] is ContentTypeOutput
    assert kwargs["model"] == "claude-opus-5-5"
    assert kwargs["max_tokens"] == 1234
    assert kwargs["system"] == PROVIDER_SYSTEM_PROMPT
    assert kwargs["messages"] == [{"role": "user", "content": "PROMPT TEXT"}]
    assert kwargs["output_config"] == {"effort": "medium"}
    # Sampling parameters are not sent (they are rejected by current Claude models).
    assert "temperature" not in kwargs


@pytest.mark.asyncio
async def test_generate_text_joins_text_blocks():
    response = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text="Hello "),
                 SimpleNamespace(type="text", text="world")],
    )
    provider, messages = make_provider(create_response=response)
    assert await provider.generate_text("p") == "Hello world"
    assert messages.calls[0][0] == "create"


@pytest.mark.asyncio
async def test_refusal_is_a_clean_non_retryable_error():
    provider, _ = make_provider(parse_response=SimpleNamespace(stop_reason="refusal", parsed_output=None))
    with pytest.raises(AIProviderError) as exc:
        await provider.generate_structured("p", ContentTypeOutput)
    assert exc.value.retryable is False
    assert "declined" in str(exc.value)


@pytest.mark.asyncio
async def test_truncated_output_is_reported():
    provider, _ = make_provider(parse_response=SimpleNamespace(stop_reason="max_tokens", parsed_output=None))
    with pytest.raises(AIProviderError, match="CLAUDE_MAX_TOKENS"):
        await provider.generate_structured("p", ContentTypeOutput)


@pytest.mark.asyncio
async def test_missing_parsed_output_is_retryable():
    provider, _ = make_provider(parse_response=SimpleNamespace(stop_reason="end_turn", parsed_output=None))
    with pytest.raises(AIProviderError) as exc:
        await provider.generate_structured("p", ContentTypeOutput)
    assert exc.value.retryable is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error, retryable, text",
    [
        (anthropic.AuthenticationError("bad key", response=_response(401), body=None), False, "ANTHROPIC_API_KEY"),
        (anthropic.BadRequestError("bad request", response=_response(400), body=None), False, "rejected"),
        (anthropic.RateLimitError("slow down", response=_response(429), body=None), True, "rate limit"),
        (anthropic.InternalServerError("boom", response=_response(500), body=None), True, "500"),
        (anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api.anthropic.com")), True, "reach"),
    ],
)
async def test_sdk_errors_map_to_provider_errors(error, retryable, text):
    provider, _ = make_provider(error=error)
    with pytest.raises(AIProviderError) as exc:
        await provider.generate_structured("p", ContentTypeOutput)
    assert exc.value.retryable is retryable
    assert text in str(exc.value)
    assert exc.value.provider == "claude"


def test_non_retryable_provider_errors_stop_the_retry_loop():
    update = generation_failure({"retries": 0}, "Failed", AIProviderError("auth", provider="claude", retryable=False))
    assert update["retries"] >= MAX_RETRIES

    update = generation_failure({"retries": 0}, "Failed", AIProviderError("busy", provider="claude", retryable=True))
    assert update["retries"] == 1


# ─── Inside the existing LangGraph workflow ──────────────────────────────────

@pytest.mark.asyncio
async def test_claude_provider_runs_inside_existing_content_selection_graph():
    from app.ai.services.ai_orchestrator import AIOrchestrator

    selection = ContentSelectionOutput(opportunities=[{
        "id": "opt-1", "content_type": "Carousel", "platform": "LinkedIn", "title": "LedgerLeaf for designers",
        "summary": "s", "whyInteresting": "w", "keyPoints": ["GST invoices"], "potentialAudience": "Freelance designers",
    }])
    provider, messages = make_provider(
        parse_response=SimpleNamespace(stop_reason="end_turn", parsed_output=selection),
        create_response=SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="analysis")]),
    )
    with patch("app.ai.nodes.content_selection_nodes.get_provider", return_value=provider):
        result = await AIOrchestrator().run_content_selection("LedgerLeaf is a bookkeeping app.", "Carousel")

    assert result["opportunities"][0]["content_type"] == "Carousel"
    for _, kwargs in messages.calls:
        prompt = kwargs["messages"][0]["content"]
        assert "LedgerLeaf is a bookkeeping app." in prompt
        assert "DEMO MODE" not in prompt


@pytest.mark.asyncio
async def test_diagnostics_never_expose_anthropic_key(authenticated_client):
    secret = "sk-ant-super-secret-value"
    with patch("app.core.config.settings.AI_PROVIDER", "claude"), \
         patch("app.core.config.settings.ANTHROPIC_API_KEY", secret):
        response = await authenticated_client.get("/api/diagnostics")
    assert response.status_code == 200
    body = response.text
    assert secret not in body
    assert response.json()["ai"]["provider"] == "claude"
    assert response.json()["ai"]["status"] == "Ready"
