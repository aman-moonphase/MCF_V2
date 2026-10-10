"""Claude model configuration: documented default, explicit overrides passed through unchanged, clear
configuration errors, and no fallback to Demo Mode. No network calls and no real API key are used."""
from pathlib import Path
from unittest.mock import patch

import pytest

from app.ai.config import build_ai_config, claude_model_problem
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.demo_provider import DemoProvider
from app.ai.providers.factory import get_configured_provider
from app.core.config import DEFAULT_CLAUDE_MODEL, Settings

FAKE_KEY = "test-key-not-real"


def claude_settings(**overrides):
    values = {"AI_PROVIDER": "claude", "ANTHROPIC_API_KEY": FAKE_KEY, **overrides}
    patches = [patch(f"app.core.config.settings.{k}", v) for k, v in values.items()]
    for p in patches:
        p.start()
    return patches


def stop(patches):
    for p in patches:
        p.stop()


def test_default_model_is_claude_sonnet_5_5():
    assert DEFAULT_CLAUDE_MODEL == "claude-sonnet-5-5"
    assert Settings.model_fields["CLAUDE_MODEL"].default == "claude-sonnet-5-5"
    assert ClaudeProvider.__init__.__defaults__[0] == "claude-sonnet-5-5"  # model_name default stays in sync


def test_default_reaches_the_request_unchanged():
    patches = claude_settings(CLAUDE_MODEL=DEFAULT_CLAUDE_MODEL)
    try:
        config = build_ai_config()
        provider = get_configured_provider()
    finally:
        stop(patches)
    assert config.provider == "claude" and config.model_name == "claude-sonnet-5-5"
    assert isinstance(provider, ClaudeProvider)
    assert provider._request_kwargs("p")["model"] == "claude-sonnet-5-5"


@pytest.mark.parametrize("model", ["claude-opus-5", "claude-sonnet-5", "claude-opus-5-5", "claude-haiku-5-5"])
def test_explicit_model_is_passed_through_unchanged(model):
    patches = claude_settings(CLAUDE_MODEL=model)
    try:
        provider = get_configured_provider()
    finally:
        stop(patches)
    assert provider.model_name == model
    assert provider._request_kwargs("p")["model"] == model


def test_model_can_be_set_from_the_environment(monkeypatch):
    monkeypatch.setenv("CLAUDE_MODEL", "claude-opus-5")
    assert Settings().CLAUDE_MODEL == "claude-opus-5"
    monkeypatch.delenv("CLAUDE_MODEL")
    assert Settings().CLAUDE_MODEL == "claude-sonnet-5-5"  # backend/.env does not override the default


@pytest.mark.parametrize("bad", ["", "   ", " claude-sonnet-5", "claude sonnet 5"])
def test_malformed_model_is_a_clear_configuration_error_not_a_fallback(bad):
    assert "CLAUDE_MODEL" in claude_model_problem(bad)
    patches = claude_settings(CLAUDE_MODEL=bad)
    try:
        with pytest.raises(ValueError, match="CLAUDE_MODEL"):
            get_configured_provider()
    finally:
        stop(patches)


def test_missing_key_never_falls_back_to_demo():
    patches = claude_settings(ANTHROPIC_API_KEY=None)
    try:
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            get_configured_provider()
    finally:
        stop(patches)


def test_demo_mode_is_still_the_default_provider():
    assert Settings.model_fields["AI_PROVIDER"].default == "demo"
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        assert isinstance(get_configured_provider(), DemoProvider)


def test_env_example_documents_the_default_model():
    example = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert "CLAUDE_MODEL=claude-sonnet-5-5\n" in example
    assert "AI_PROVIDER=demo" in example and "ANTHROPIC_API_KEY=\n" in example  # no key value shipped


@pytest.mark.asyncio
async def test_diagnostics_reports_model_and_configuration_problems_without_the_key(authenticated_client):
    patches = claude_settings(CLAUDE_MODEL="claude-sonnet-5")
    try:
        ok = (await authenticated_client.get("/api/diagnostics")).json()
    finally:
        stop(patches)
    assert ok["ai"]["provider"] == "claude" and ok["ai"]["model"] == "claude-sonnet-5" and ok["ai"]["status"] == "Ready"
    assert FAKE_KEY not in str(ok)

    patches = claude_settings(CLAUDE_MODEL=" ")
    try:
        bad = (await authenticated_client.get("/api/diagnostics")).json()
    finally:
        stop(patches)
    assert bad["ai"]["status"] == "Not configured" and "CLAUDE_MODEL" in bad["ai"]["message"]
