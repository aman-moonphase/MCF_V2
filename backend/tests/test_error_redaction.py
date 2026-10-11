"""Error responses must never carry secret-shaped text (Step 11 audit).

Provider SDKs put credential fragments in their error messages (e.g. OpenAI: "Incorrect API key provided:
sk-proj-********abcd"), database drivers put connection URLs in theirs, and MCF returns exception text in some 500/422
details. Every HTTP error body is therefore redacted at one choke point (app/core/redaction.py).
"""
from unittest.mock import patch

import pytest

from app.core.config import settings
from app.core.redaction import redact, redact_payload
from tests.test_generate_content import gen_url, ready_project

CONFIGURED_KEY = "configured-secret-value-0123456789abcdef"


class FailingProvider:
    """A real-provider stand-in whose SDK error text contains credentials and a connection URL."""

    def __init__(self, message: str):
        self.message = message

    async def generate_structured(self, prompt, schema):
        raise Exception(self.message)

    async def generate_text(self, prompt):
        raise Exception(self.message)


@pytest.mark.asyncio
async def test_provider_error_text_is_redacted_in_the_http_response(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", CONFIGURED_KEY)
    project_id, _, _ = await ready_project(authenticated_client)
    message = ("Error code: 401 - {'error': {'message': 'Incorrect API key provided: sk-proj-********abcd. You can find your "
               f"API key at https://platform.openai.com/account/api-keys.'}} | key={CONFIGURED_KEY} | "
               "Authorization: Bearer abcdefghijklmnop12345 | postgresql+asyncpg://mcf_user:hunter2pass@db.internal:5444/mcf_db")
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=FailingProvider(message)):
        res = await authenticated_client.post(gen_url(project_id), json={})
    assert res.status_code == 500, res.text
    for fragment in ("sk-proj", "abcd", CONFIGURED_KEY, "abcdefghijklmnop12345", "hunter2pass", "db.internal", "mcf_user"):
        assert fragment not in res.text, f"{fragment!r} leaked in the response"
    assert "LinkedIn post generation failed" in res.json()["detail"]  # still a useful, specific message


def test_redact_patterns_and_configured_secrets(monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "oa-custom-key-value-98765")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "smtp-pass-4321-xyz")
    cases = {
        "Incorrect API key provided: sk-proj-********abcd.": "sk-proj",
        "x-api-key: sk-ant-api03-AbCdEf_123-456": "sk-ant",
        "bad key oa-custom-key-value-98765 given": "oa-custom-key",
        "login failed for smtp-pass-4321-xyz": "smtp-pass",
        "Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig": "eyJhbGci",
        "could not connect to postgresql://user:secretpw@host:5432/db": "secretpw",
        "password=hunter2hunter2": "hunter2hunter2",
    }
    for text, secret in cases.items():
        assert secret not in redact(text), text
        assert "[redacted]" in redact(text), text
    # Ordinary messages are untouched, including words that merely look similar.
    plain = "The post is over the platform's character limit (3,200 of 3,000). Ask about desk-lamp design."
    assert redact(plain) == plain
    assert redact("Evaluate the saved post (version 2) first.") == "Evaluate the saved post (version 2) first."
    assert redact(None) is None and redact("") == ""


def test_weak_configured_values_do_not_garble_ordinary_messages(monkeypatch):
    # A local database password that is literally "password" must not turn login errors into "…or [redacted]".
    monkeypatch.setattr(settings, "POSTGRES_PASSWORD", "password")
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "admin")
    for message in ("Incorrect email or password", "Invalid or expired password reset token", "Use a different admin account"):
        assert redact(message) == message
    # Long random values are still removed anywhere they appear.
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "Xk9f2LmQ7vTnB4")
    assert "Xk9f2LmQ7vTnB4" not in redact("SMTP login failed for Xk9f2LmQ7vTnB4 on host")
    # …and a weak value is still caught when it is labelled.
    assert "password" not in redact("connect failed: password=password").split("=", 1)[1]


def test_structured_details_are_redacted_recursively():
    payload = {"message": "failed sk-live-abcdef123456", "reasons": [{"code": "x", "message": "token=abcdef123456 bad"}], "lock_version": 3}
    cleaned = redact_payload(payload)
    assert "sk-live" not in str(cleaned) and "abcdef123456" not in str(cleaned)
    assert cleaned["lock_version"] == 3 and cleaned["reasons"][0]["code"] == "x"


@pytest.mark.asyncio
async def test_validation_and_not_found_errors_are_unchanged(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={})
    assert res.status_code == 422 and isinstance(res.json()["detail"], list)
    missing = await authenticated_client.get("/api/projects/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404 and missing.json() == {"detail": "Project not found"}


@pytest.mark.asyncio
async def test_auth_errors_are_unchanged(client):
    res = await client.get("/api/settings/me")
    assert res.status_code in (401, 403) and "detail" in res.json()
