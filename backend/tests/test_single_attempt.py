"""Single-attempt mode (settings.AI_SINGLE_ATTEMPT) for controlled real-AI tests: one user action makes at most
one provider request per AI step — no application-level regeneration and no SDK retries — whether the output
fails validation or the API errors. With the mode off, normal retries are unchanged.

All providers are fakes that count calls; no network, no real key.
"""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.graphs.generation_graph import run_linkedin_generation
from app.ai.nodes.common import MAX_RETRIES, max_attempts, sdk_max_retries
from app.ai.providers.base import AIProviderError
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.factory import get_configured_provider
from app.core.config import settings
from tests.ai.test_generation_graph import POST, STATE
from tests.test_generate_content import GOOD_POST, gen_url, ready_project

INVALID = {**POST, "body": "LedgerLeaf is used by 10,000 designers."}  # invented figure → fails validation


class CountingProvider:
    def __init__(self, *outcomes, text="Source analysis."):
        self.outcomes, self.text, self.structured_calls, self.text_calls = list(outcomes), text, 0, 0

    async def generate_structured(self, prompt, schema):
        self.structured_calls += 1
        outcome = self.outcomes[min(self.structured_calls, len(self.outcomes)) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return schema.model_validate(outcome)

    async def generate_text(self, prompt):
        self.text_calls += 1
        return self.text


@pytest.fixture
def single_attempt(monkeypatch):
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)


async def run_post(provider):
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        return await run_linkedin_generation(STATE)


# ─── The switch ─────────────────────────────────────────────────────────────

def test_limits_follow_the_setting(monkeypatch):
    assert max_attempts() == MAX_RETRIES == 3 and sdk_max_retries() == 2  # default: normal retries
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)
    assert max_attempts() == 1 and sdk_max_retries() == 0


def test_claude_client_sdk_retries(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "fake-key-for-tests-only")
    assert get_configured_provider().client.max_retries == 2
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)
    provider = get_configured_provider()
    assert isinstance(provider, ClaudeProvider) and provider.client.max_retries == 0


# ─── Single attempt: at most one request ────────────────────────────────────

@pytest.mark.asyncio
async def test_validation_failure_is_not_regenerated(single_attempt):
    provider = CountingProvider(INVALID, POST)
    with pytest.raises(RuntimeError, match="figure"):
        await run_post(provider)
    assert provider.structured_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("error", [
    AIProviderError("Claude rate limit reached.", provider="claude", retryable=True),
    AIProviderError("Claude request timed out.", provider="claude", retryable=True),
    AIProviderError("Claude authentication failed.", provider="claude", retryable=False),
    RuntimeError("unexpected"),
])
async def test_api_errors_are_not_retried(single_attempt, error):
    provider = CountingProvider(error, POST)
    with pytest.raises(RuntimeError, match="Generation failed"):
        await run_post(provider)
    assert provider.structured_calls == 1


@pytest.mark.asyncio
async def test_success_uses_exactly_one_request(single_attempt):
    provider = CountingProvider(POST)
    result = await run_post(provider)
    assert provider.structured_calls == 1 and result["post"]["hook"] == POST["hook"]


@pytest.mark.asyncio
async def test_other_ai_steps_also_make_one_attempt(single_attempt):
    from app.ai.graphs.product_understanding_graph import run_product_understanding
    from app.ai.graphs.strategy_graph import run_promotion_strategy

    pu = CountingProvider(AIProviderError("overloaded", provider="claude", retryable=True))
    with patch("app.ai.nodes.product_understanding_nodes.get_provider", return_value=pu), pytest.raises(RuntimeError):
        await run_product_understanding("Product: TaskNest - a task app for small teams.")
    assert pu.structured_calls == 1 and pu.text_calls <= 1

    strategy = CountingProvider(AIProviderError("overloaded", provider="claude", retryable=True))
    with patch("app.ai.graphs.competitor_graph.get_provider", return_value=strategy), pytest.raises(RuntimeError):
        await run_promotion_strategy({"prompt_context": [], "allowed_refs": [], "corpus": "", "meta": {}, "demo_input": {}})
    assert strategy.structured_calls == 1


@pytest.mark.asyncio
async def test_one_click_makes_one_request_through_the_api(authenticated_client, monkeypatch, single_attempt):
    project_id, _, s = await ready_project(authenticated_client)
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs["model"])
        post = {**INVALID, "body": "LedgerLeaf is used by 10,000 designers.", "pillar": s["strategy"]["content_pillars"][0]["name"]}
        return SimpleNamespace(stop_reason="end_turn", parsed_output=LinkedInPostOutput.model_validate(post),
                               usage=SimpleNamespace(input_tokens=1500, output_tokens=400))

    provider = ClaudeProvider(api_key="fake-key-for-tests-only", model_name="claude-sonnet-5-5",
                              client=SimpleNamespace(messages=SimpleNamespace(parse=parse)), max_retries=0)
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 500 and "figure" in res.json()["detail"]
    assert calls == ["claude-sonnet-5-5"]  # exactly one request, no regeneration
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"] is None  # nothing saved


# ─── Normal mode unchanged ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_normal_mode_still_regenerates_after_validation_failure():
    provider = CountingProvider(INVALID, POST)
    result = await run_post(provider)
    assert provider.structured_calls == 2 and result["post"]["body"] == POST["body"]


@pytest.mark.asyncio
async def test_normal_mode_still_retries_retryable_errors_and_stops_on_fatal_ones():
    retryable = CountingProvider(AIProviderError("overloaded", provider="claude", retryable=True))
    with pytest.raises(RuntimeError):
        await run_post(retryable)
    assert retryable.structured_calls == MAX_RETRIES == 3

    fatal = CountingProvider(AIProviderError("auth", provider="claude", retryable=False))
    with pytest.raises(RuntimeError):
        await run_post(fatal)
    assert fatal.structured_calls == 1


@pytest.mark.asyncio
async def test_mode_endpoint_reports_single_attempt(authenticated_client, monkeypatch):
    assert (await authenticated_client.get("/api/ai/mode")).json()["single_attempt"] is False
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)
    assert (await authenticated_client.get("/api/ai/mode")).json()["single_attempt"] is True


def test_good_post_fixture_is_valid():
    LinkedInPostOutput.model_validate(GOOD_POST)
