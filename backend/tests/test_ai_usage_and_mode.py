"""Pre-flight safeguards for real-AI tests: per-request usage capture, estimated cost, persistence on the saved post
(and through manual edits), no invented usage in Demo Mode, and a safe provider-mode endpoint.

Every Claude call is a fake client — no network, no real key, no credits.
"""
import logging
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy import select

from app.ai.generation_context import generation_context
from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.providers.base import AIProviderError
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.usage import CLAUDE_RATES, collect_usage, estimate_cost_usd, summarize_usage
from app.core.config import settings
from app.models.generated_content import GeneratedContent
from tests.test_generate_content import GOOD_POST, gen_url, generate, ready_project

FAKE_KEY = "fake-key-for-tests-only"
USAGE = SimpleNamespace(input_tokens=1800, output_tokens=420, cache_creation_input_tokens=None, cache_read_input_tokens=None)


class FakeMessages:
    """Returns queued responses (or raises queued exceptions); records nothing about the prompt."""

    def __init__(self, *outcomes):
        self.outcomes, self.calls = list(outcomes), 0

    async def parse(self, **kwargs):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def response(post: dict, usage=USAGE):
    return SimpleNamespace(stop_reason="end_turn", parsed_output=LinkedInPostOutput.model_validate(post), usage=usage)


def fake_claude(*outcomes, model="claude-sonnet-5-5"):
    messages = FakeMessages(*outcomes)
    return ClaudeProvider(api_key=FAKE_KEY, model_name=model, client=SimpleNamespace(messages=messages)), messages


# ─── Cost estimates ─────────────────────────────────────────────────────────

def test_cost_estimates_use_central_model_rates():
    assert estimate_cost_usd("claude-sonnet-5-5", 1_000_000, 0) == 2.0
    assert estimate_cost_usd("claude-sonnet-5-5", 0, 1_000_000) == 10.0
    assert estimate_cost_usd("claude-sonnet-5-5", 1800, 420) == round((1800 * 2 + 420 * 10) / 1e6, 6) == 0.0078
    assert estimate_cost_usd("claude-opus-5-5", 1000, 1000) == round((1000 * 4 + 1000 * 20) / 1e6, 6)


def test_cache_tokens_are_priced_when_reported():
    rates = CLAUDE_RATES["claude-sonnet-5-5"]
    cost = estimate_cost_usd("claude-sonnet-5-5", 1000, 100, cache_creation_tokens=4000, cache_read_tokens=20000)
    assert cost == round((1000 * rates.input + 100 * rates.output + 4000 * rates.cache_write + 20000 * rates.cache_read) / 1e6, 6)
    assert cost > estimate_cost_usd("claude-sonnet-5-5", 1000, 100)


def test_no_invented_cost():
    assert estimate_cost_usd("claude-some-future-model", 1000, 1000) is None  # no configured rate → no estimate
    assert estimate_cost_usd("claude-sonnet-5-5", None, None) is None  # no tokens reported → no estimate
    assert summarize_usage([], generated_version=1) is None  # no requests (Demo Mode) → no usage at all


# ─── Capture in the provider ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_each_request_is_recorded_with_stage_attempt_tokens_and_duration():
    provider, _ = fake_claude(response(GOOD_POST, SimpleNamespace(input_tokens=1000, output_tokens=200,
                                                                    cache_creation_input_tokens=300, cache_read_input_tokens=50)))
    with collect_usage() as records, generation_context({"retries": 1}, "generate-content"):
        await provider.generate_structured("PROMPT", LinkedInPostOutput)
    (r,) = records
    assert r["provider"] == "claude" and r["model"] == "claude-sonnet-5-5"
    assert r["stage"] == "generate-content" and r["attempt"] == 2 and r["status"] == "ok"
    assert (r["input_tokens"], r["output_tokens"], r["cache_creation_input_tokens"], r["cache_read_input_tokens"]) == (1000, 200, 300, 50)
    assert isinstance(r["duration_ms"], int) and r["duration_ms"] >= 0
    assert r["estimated_cost_usd"] == estimate_cost_usd("claude-sonnet-5-5", 1000, 200, 300, 50)


@pytest.mark.asyncio
async def test_failed_requests_are_recorded_without_tokens_or_cost():
    provider, _ = fake_claude(RuntimeError("network down"))
    with collect_usage() as records, generation_context({}, "generate-content"):
        with pytest.raises(RuntimeError):
            await provider.generate_structured("PROMPT", LinkedInPostOutput)
    (r,) = records
    assert r["status"] == "error" and r["error_type"] == "RuntimeError"
    assert r["input_tokens"] is None and r["output_tokens"] is None and r["estimated_cost_usd"] is None


@pytest.mark.asyncio
async def test_unreported_token_fields_stay_none_not_zero():
    provider, _ = fake_claude(response(GOOD_POST, SimpleNamespace(input_tokens=10, output_tokens=5)))
    with collect_usage() as records:
        await provider.generate_structured("PROMPT", LinkedInPostOutput)
    assert records[0]["cache_read_input_tokens"] is None and records[0]["cache_creation_input_tokens"] is None


@pytest.mark.asyncio
async def test_logs_hold_metadata_only(caplog):
    provider, _ = fake_claude(response(GOOD_POST))
    caplog.set_level(logging.INFO, logger="mcf.ai.usage")
    secret_prompt = "SOURCE TEXT: confidential roadmap for StudioDesk"
    with generation_context({}, "generate-content"):
        await provider.generate_structured(secret_prompt, LinkedInPostOutput)
    log = "\n".join(r.getMessage() for r in caplog.records)
    assert "ai_request" in log and "model=claude-sonnet-5-5" in log and "input_tokens=1800" in log
    assert "confidential" not in log and FAKE_KEY not in log and GOOD_POST["body"] not in log


# ─── Persistence on the saved post ──────────────────────────────────────────

async def generate_with_claude(client, project_id, monkeypatch, provider):
    from unittest.mock import patch
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")  # recorded as provider; embeddings stay demo
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        res = await client.post(gen_url(project_id), json={})
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    return res


@pytest.mark.asyncio
async def test_usage_is_stored_with_the_generated_version_and_survives_refresh(authenticated_client, monkeypatch):
    project_id, _, s = await ready_project(authenticated_client)
    provider, messages = fake_claude(response({**GOOD_POST, "pillar": s["strategy"]["content_pillars"][0]["name"]}))
    res = await generate_with_claude(authenticated_client, project_id, monkeypatch, provider)
    assert res.status_code == 200, res.text
    draft = res.json()["draft"]
    usage = draft["usage"]
    assert draft["provider"] == "claude" and draft["is_demo"] is False and messages.calls == 1
    assert usage["generated_version"] == draft["version"] == 1
    assert usage["request_count"] == 1 and usage["failed_requests"] == 0 and usage["models"] == ["claude-sonnet-5-5"]
    assert usage["totals"] == {"input_tokens": 1800, "output_tokens": 420, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}
    assert usage["estimated_cost_usd"] == 0.0078 and usage["cost_is_estimate"] is True and "Estimate only" in usage["cost_note"]
    assert usage["requests"][0]["stage"] == "generate-content" and usage["requests"][0]["attempt"] == 1

    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as fresh:  # a refresh / new session reads the same stored usage
        row = (await fresh.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalar_one()
        assert row.usage["estimated_cost_usd"] == 0.0078 and row.usage["generated_version"] == 1
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"]["usage"] == usage


@pytest.mark.asyncio
async def test_retried_requests_are_all_counted(authenticated_client, monkeypatch):
    project_id, _, s = await ready_project(authenticated_client)
    pillar = s["strategy"]["content_pillars"][0]["name"]
    invalid = {**GOOD_POST, "pillar": pillar, "body": "LedgerLeaf is used by 10,000 designers."}  # invented figure → retried
    provider, messages = fake_claude(response(invalid), response({**GOOD_POST, "pillar": pillar}))
    res = await generate_with_claude(authenticated_client, project_id, monkeypatch, provider)
    usage = res.json()["draft"]["usage"]
    assert messages.calls == 2 and usage["request_count"] == 2
    assert [r["attempt"] for r in usage["requests"]] == [1, 2]
    assert usage["totals"]["input_tokens"] == 3600 and usage["estimated_cost_usd"] == round(2 * 0.0078, 6)


@pytest.mark.asyncio
async def test_failed_generation_persists_nothing(authenticated_client, monkeypatch):
    project_id, _, _ = await ready_project(authenticated_client)
    provider, _ = fake_claude(*[AIProviderError("Claude authentication failed.", provider="claude")] * 3)
    res = await generate_with_claude(authenticated_client, project_id, monkeypatch, provider)
    assert res.status_code == 500
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"] is None


@pytest.mark.asyncio
async def test_manual_edits_keep_the_generation_usage(authenticated_client, monkeypatch):
    project_id, _, s = await ready_project(authenticated_client)
    provider, _ = fake_claude(response({**GOOD_POST, "pillar": s["strategy"]["content_pillars"][0]["name"]}))
    usage = (await generate_with_claude(authenticated_client, project_id, monkeypatch, provider)).json()["draft"]["usage"]
    edited = await authenticated_client.patch(gen_url(project_id), json={"cta": "Message us to try LedgerLeaf.", "version": 1})
    assert edited.status_code == 200, edited.text
    draft = edited.json()["draft"]
    assert draft["version"] == 2 and draft["edited"] is True
    assert draft["usage"] == usage and draft["usage"]["generated_version"] == 1  # describes the generation, not the edit


@pytest.mark.asyncio
async def test_demo_mode_records_no_usage(authenticated_client, caplog):
    caplog.set_level(logging.INFO, logger="mcf.ai.usage")
    project_id, _, _ = await ready_project(authenticated_client)
    state = await generate(authenticated_client, project_id)
    assert state["draft"]["is_demo"] is True and state["draft"]["usage"] is None
    assert not any("ai_request" in r.getMessage() for r in caplog.records)


# ─── Provider-mode endpoint ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_mode_endpoint_reports_demo(authenticated_client):
    mode = (await authenticated_client.get("/api/ai/mode")).json()
    assert mode == {"mode": "demo", "provider": "demo", "model": None, "configured": True, "configuration_problem": None,
                    "may_incur_charges": False, "connection_verified": False, "cost_estimates_available": False,
                    "single_attempt": False}


@pytest.mark.asyncio
async def test_mode_endpoint_reports_real_ai_without_secrets(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", FAKE_KEY)
    res = await authenticated_client.get("/api/ai/mode")
    mode = res.json()
    assert mode["mode"] == "real" and mode["provider"] == "claude" and mode["model"] == "claude-sonnet-5-5"
    assert mode["configured"] is True and mode["may_incur_charges"] is True and mode["cost_estimates_available"] is True
    assert mode["connection_verified"] is False  # configuration only — never a claimed live check
    assert FAKE_KEY not in res.text and "key" not in {k.lower() for k in mode}


@pytest.mark.asyncio
async def test_mode_endpoint_reports_misconfiguration(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", None)
    mode = (await authenticated_client.get("/api/ai/mode")).json()
    assert mode["mode"] == "real" and mode["configured"] is False and "ANTHROPIC_API_KEY" in mode["configuration_problem"]
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", FAKE_KEY)
    monkeypatch.setattr(settings, "CLAUDE_MODEL", " ")
    mode = (await authenticated_client.get("/api/ai/mode")).json()
    assert mode["configured"] is False and "CLAUDE_MODEL" in mode["configuration_problem"]


@pytest.mark.asyncio
async def test_mode_endpoint_requires_login(client):
    assert (await client.get("/api/ai/mode")).status_code == 401
