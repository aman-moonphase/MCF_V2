"""Upload and ingestion hardening (Step 11 audit): bounded uploads, clear client errors instead of 500s.

- A PDF above MAX_UPLOAD_BYTES is refused with 413 on both upload routes, is never fully read, and leaves no file behind.
- A corrupt PDF or an unreachable URL is the user's input problem: 422 with a clear message (not 500 with repr(e)).
- Oversized pasted text is refused before it is stored.
"""
import os
from uuid import UUID

import pytest
import requests
from sqlalchemy import func, select

from app.api.routes import sources as sources_route
from app.core.config import settings
from app.models.source import SourceDocument
from tests.test_promotion_strategy import make_product
from tests.test_rag_research_grounding import make_project


@pytest.fixture
def upload_dir(tmp_path, monkeypatch):
    """Route uploads to a temp dir so we can prove nothing is left behind."""
    directory = tmp_path / "uploads"
    original = sources_route.temp_upload_path
    monkeypatch.setattr(sources_route, "TEMP_UPLOAD_DIR", str(directory))
    monkeypatch.setattr(sources_route, "temp_upload_path", lambda upload_dir=None: original(str(directory)))
    return directory


async def source_count(db, project_id):
    db.expire_all()
    return (await db.execute(select(func.count(SourceDocument.id)).where(SourceDocument.project_id == UUID(project_id)))).scalar()


@pytest.mark.asyncio
async def test_oversized_pdf_is_refused_and_leaves_nothing(authenticated_client, db_session, upload_dir, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024 * 1024)  # 1 MB for the test
    project_id = await make_project(authenticated_client)
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "pdf"},
                                          files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024), "application/pdf")})
    assert res.status_code == 413 and "too large" in res.json()["detail"] and "1 MB" in res.json()["detail"]
    assert not list(upload_dir.glob("*")) if upload_dir.exists() else True  # the partial file was removed
    assert await source_count(db_session, project_id) == 0  # nothing was recorded

    within = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "pdf"},
                                             files={"file": ("small.pdf", b"%PDF-1.4 not a real pdf", "application/pdf")})
    assert within.status_code == 422  # under the limit: processed (and rejected only because it is not a real PDF)


@pytest.mark.asyncio
async def test_oversized_competitor_evidence_pdf_is_refused(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "MAX_UPLOAD_BYTES", 1024 * 1024)
    project_id, product_id = await make_product(authenticated_client)
    competitor = (await authenticated_client.post(f"/api/products/{product_id}/competitors", json={"name": "BigPDF Ltd"})).json()
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/evidence",
                                          data={"evidence_type": "pdf"},
                                          files={"file": ("big.pdf", b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024), "application/pdf")})
    assert res.status_code == 413 and "too large" in res.json()["detail"]


@pytest.mark.asyncio
async def test_corrupt_pdf_is_a_clear_user_error(authenticated_client, db_session, upload_dir):
    project_id = await make_project(authenticated_client)
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "pdf"},
                                          files={"file": ("broken.pdf", b"this is not a pdf at all", "application/pdf")})
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert "Invalid PDF" in detail and "Traceback" not in detail and "ValueError(" not in detail
    assert not list(upload_dir.glob("*"))  # the uploaded file was removed
    status_ = (await db_session.execute(select(SourceDocument.status).where(SourceDocument.project_id == UUID(project_id)))).scalars().all()
    assert status_ == ["failed"]  # recorded as failed, so Diagnostics can list it


@pytest.mark.asyncio
async def test_unreachable_url_is_a_clear_user_error(authenticated_client, monkeypatch):
    from app.core import url_safety

    def unreachable(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr(url_safety, "safe_get", unreachable)  # imported inside the extractor at call time
    monkeypatch.setattr(sources_route, "validate_public_url", lambda url, allow_private=False: url)
    project_id = await make_project(authenticated_client)
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest",
                                          data={"source_type": "url", "content": "https://example.com/page"})
    assert res.status_code == 422 and "Failed to fetch URL" in res.json()["detail"], res.text


@pytest.mark.asyncio
async def test_oversized_text_is_refused_before_it_is_stored(authenticated_client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "RAG_MAX_SOURCE_CHARS", 1000)
    project_id = await make_project(authenticated_client)
    res = await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest",
                                          data={"source_type": "text", "content": "word " * 1000})
    assert res.status_code == 422 and "too large" in res.json()["detail"] and "limit is 1,000" in res.json()["detail"]
    assert await source_count(db_session, project_id) == 0  # no giant raw_text row was written
