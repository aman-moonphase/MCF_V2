"""Sources get readable names (they appear as evidence labels): a page's host and path, or "Pasted text"."""
import pytest

from app.api.routes.sources import url_display_name
from app.core.config import settings


def test_url_sources_are_named_by_host_and_path():
    assert url_display_name("https://plausible.io/about") == "plausible.io/about"
    assert url_display_name("https://plausible.io/data-policy/") == "plausible.io/data-policy"
    assert url_display_name("https://example.com") == "example.com"
    assert len(url_display_name("https://example.com/" + "a" * 500)) <= 200


@pytest.mark.asyncio
async def test_pasted_text_sources_are_named_pasted_text(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    created = await authenticated_client.post("/api/projects", json={"title": "n", "source_type": "Text Idea", "source_reference": "x"})
    project_id = created.json()["id"]
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": "Acme is a tool for makers."})
    assert res.status_code == 200, res.text
    sources = (await authenticated_client.get(f"/api/projects/{project_id}/sources")).json()["sources"]
    assert [s["name"] for s in sources] == ["Pasted text"]
