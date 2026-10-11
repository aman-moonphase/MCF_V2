"""Regression tests for the Phase 1 minimum security fixes."""
import os
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.api.routes import sources as sources_route
from app.core.config import Settings, _LEAKED_DEFAULT_SECRET_KEY, settings
from app.core.url_safety import UnsafeURLError, safe_get, validate_public_url

DB_URL = "postgresql+asyncpg://u:p@localhost:5432/mcf_db"


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, DATABASE_URL=DB_URL, **kwargs)


# ─── 1-2. JWT secret ─────────────────────────────────────────────────────────

def test_secret_key_is_never_the_old_hardcoded_default():
    assert settings.SECRET_KEY != _LEAKED_DEFAULT_SECRET_KEY
    assert len(settings.SECRET_KEY) >= 32


def test_leaked_default_secret_is_rejected():
    with pytest.raises(ValidationError, match="old hardcoded default"):
        _settings(ENV="development", SECRET_KEY=_LEAKED_DEFAULT_SECRET_KEY)


def test_production_requires_secret_key():
    with pytest.raises(ValidationError, match="SECRET_KEY must be set"):
        _settings(ENV="production", SECRET_KEY=None)


def test_short_secret_key_is_rejected():
    with pytest.raises(ValidationError, match="at least 32"):
        _settings(ENV="production", SECRET_KEY="too-short")


def test_production_accepts_secret_from_environment():
    key = "k" * 64
    assert _settings(ENV="production", SECRET_KEY=key).SECRET_KEY == key


def test_development_without_secret_gets_random_ephemeral_key():
    first = _settings(ENV="development", SECRET_KEY=None).SECRET_KEY
    second = _settings(ENV="development", SECRET_KEY=None).SECRET_KEY
    assert first and second and first != second
    assert _LEAKED_DEFAULT_SECRET_KEY not in (first, second)


def test_secret_key_is_read_from_environment_variable(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "e" * 48)
    assert _settings(ENV="production").SECRET_KEY == "e" * 48


# ─── 3. Upload filename sanitisation ─────────────────────────────────────────

@pytest.mark.parametrize("filename", [
    "../../app/main.py", "..\\..\\evil.pdf", "/etc/passwd", "C:\\Windows\\win.ini", "a/../../b.pdf", "", None,
])
def test_display_name_cannot_contain_a_path(filename):
    name = sources_route.safe_display_name(filename)
    assert "/" not in name and "\\" not in name and ".." not in name.replace("...", "")
    assert name


def test_temp_upload_path_stays_inside_upload_dir(tmp_path):
    path = sources_route.temp_upload_path(str(tmp_path))
    assert os.path.dirname(path) == os.path.realpath(str(tmp_path))
    assert path.endswith(".pdf")


@pytest.mark.asyncio
async def test_malicious_upload_filename_cannot_escape_temp_dir(authenticated_client, tmp_path, monkeypatch):
    monkeypatch.setattr(sources_route, "TEMP_UPLOAD_DIR", str(tmp_path / "uploads"))
    written = []
    original = sources_route.temp_upload_path
    monkeypatch.setattr(sources_route, "temp_upload_path", lambda upload_dir=None: written.append(original(str(tmp_path / "uploads"))) or written[-1])

    target = tmp_path / "pwned.pdf"
    project = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "File", "source_reference": "f"})
    project_id = project.json()["id"]
    res = await authenticated_client.post(
        f"/api/projects/{project_id}/sources/ingest",
        data={"source_type": "pdf"},
        files={"file": ("../pwned.pdf", b"not really a pdf", "application/pdf")},
    )
    # The fake PDF is a user error (422, not a server error), but the file was written inside the upload dir, then removed.
    assert res.status_code == 422 and "Invalid PDF" in res.json()["detail"]
    assert written and os.path.dirname(written[0]) == os.path.realpath(str(tmp_path / "uploads"))
    assert not target.exists()
    assert not os.path.exists(written[0])


# ─── 4. SSRF protection ──────────────────────────────────────────────────────

@pytest.mark.parametrize("url", [
    "file:///etc/passwd", "ftp://example.com/x", "gopher://example.com", "http://user:pass@example.com/",
    "http://127.0.0.1/", "http://127.0.0.1:8000/api/diagnostics", "http://10.0.0.5/", "http://192.168.1.1/",
    "http://172.16.0.1/", "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/", "http://100.64.0.1/", "http:///nohost",
])
def test_unsafe_urls_are_rejected(url):
    with pytest.raises(UnsafeURLError):
        validate_public_url(url)


def test_hostnames_resolving_to_private_addresses_are_rejected():
    with pytest.raises(UnsafeURLError, match="private, local, or internal"):
        validate_public_url("http://internal.example/", resolver=lambda host: ["10.1.2.3"])
    with pytest.raises(UnsafeURLError):
        validate_public_url("http://localhost/", resolver=lambda host: ["127.0.0.1", "::1"])
    # Any private answer among several is enough to reject.
    with pytest.raises(UnsafeURLError):
        validate_public_url("http://mixed.example/", resolver=lambda host: ["93.184.215.14", "127.0.0.1"])


def test_public_urls_are_allowed():
    assert validate_public_url("https://example.com/page", resolver=lambda host: ["93.184.215.14"]) == "https://example.com/page"
    assert validate_public_url("http://93.184.215.14/") == "http://93.184.215.14/"


def test_redirect_to_internal_address_is_blocked():
    redirect = MagicMock(status_code=302, headers={"Location": "http://169.254.169.254/latest/meta-data/"})
    with patch("app.core.url_safety.requests.get", return_value=redirect) as get:
        with pytest.raises(UnsafeURLError):
            safe_get("http://93.184.215.14/start")
    assert get.call_count == 1
    assert get.call_args.kwargs["allow_redirects"] is False


def test_safe_redirects_are_followed():
    redirect = MagicMock(status_code=301, headers={"Location": "/final"})
    final = MagicMock(status_code=200, headers={})
    with patch("app.core.url_safety.requests.get", side_effect=[redirect, final]) as get:
        assert safe_get("http://93.184.215.14/start") is final
    assert get.call_args_list[1].args[0] == "http://93.184.215.14/final"


@pytest.mark.asyncio
async def test_ingest_api_rejects_internal_url(authenticated_client):
    project = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "URL", "source_reference": "u"})
    res = await authenticated_client.post(
        f"/api/projects/{project.json()['id']}/sources/ingest",
        data={"source_type": "url", "content": "http://127.0.0.1:8000/api/diagnostics"},
    )
    assert res.status_code == 400
    assert "not allowed" in res.json()["detail"]
