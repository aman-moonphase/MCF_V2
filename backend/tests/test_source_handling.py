"""The complete source must reach the AI pipeline — never the 500-char source_reference preview."""
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from sqlalchemy import select

from app.models.project import Project
from app.models.source import DocumentChunk, SourceDocument
from app.services.extraction_service import ExtractionResult, ExtractionService
from app.services.source_text_service import cap_for_prompt, get_project_source_text

LONG_TEXT = " ".join(f"Sentence {i} about the LedgerLeaf bookkeeping product." for i in range(120)) + " FINAL-MARKER."


async def _create_project(client, reference: str = "LedgerLeaf") -> str:
    res = await client.post("/api/projects", json={"title": "Source test", "source_type": "Text Idea", "source_reference": reference})
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ingest(client, project_id: str, **form) -> dict:
    res = await client.post(f"/api/projects/{project_id}/sources/ingest", data=form)
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_overlong_source_reference_is_a_validation_error_not_a_crash(authenticated_client):
    res = await authenticated_client.post(
        "/api/projects", json={"title": "x", "source_type": "Text Idea", "source_reference": "a" * 501}
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_long_text_source_is_preserved_in_full(authenticated_client, db_session):
    assert len(LONG_TEXT) > 5000
    project_id = await _create_project(authenticated_client, LONG_TEXT[:495] + "...")
    result = await _ingest(authenticated_client, project_id, source_type="text", content=LONG_TEXT)
    assert result["characters_extracted"] == len(LONG_TEXT)

    doc = (await db_session.execute(select(SourceDocument).where(SourceDocument.project_id == UUID(project_id)))).scalar_one()
    assert doc.extracted_text == LONG_TEXT

    project = (await db_session.execute(select(Project).where(Project.id == UUID(project_id)))).scalar_one()
    assert await get_project_source_text(db_session, project) == LONG_TEXT


@pytest.mark.asyncio
async def test_ai_stage_receives_full_source_not_truncated_reference(authenticated_client):
    project_id = await _create_project(authenticated_client, LONG_TEXT[:495] + "...")
    await _ingest(authenticated_client, project_id, source_type="text", content=LONG_TEXT)

    with patch("app.api.routes.ai.orchestrator.run_content_type", new=AsyncMock(return_value={"recommendation": {}})) as run:
        res = await authenticated_client.post("/api/ai/content-type", json={"project_id": project_id})
    assert res.status_code == 200
    source_text = run.call_args.args[0]
    assert source_text == LONG_TEXT
    assert "FINAL-MARKER" in source_text


@pytest.mark.asyncio
async def test_pdf_extracted_text_is_kept(authenticated_client, db_session, monkeypatch):
    pdf_text = "LedgerLeaf PDF brochure. " * 100
    monkeypatch.setattr(ExtractionService, "extract_from_pdf", staticmethod(lambda content, metadata=None: ExtractionResult(pdf_text, {"num_pages": 2})))
    project_id = await _create_project(authenticated_client)
    res = await authenticated_client.post(
        f"/api/projects/{project_id}/sources/ingest",
        data={"source_type": "pdf"},
        files={"file": ("brochure.pdf", b"%PDF-1.4 fake", "application/pdf")},
    )
    assert res.status_code == 200, res.text
    doc = (await db_session.execute(select(SourceDocument).where(SourceDocument.project_id == UUID(project_id)))).scalar_one()
    assert doc.extracted_text == pdf_text
    assert doc.name == "brochure.pdf"


@pytest.mark.asyncio
async def test_url_extracted_text_is_kept(authenticated_client, db_session, monkeypatch):
    page_text = "LedgerLeaf landing page text. " * 50
    monkeypatch.setattr(ExtractionService, "extract_from_url", staticmethod(lambda url, metadata=None: ExtractionResult(page_text, {"source_url": url})))
    project_id = await _create_project(authenticated_client)
    # A public IP literal: passes SSRF validation without a DNS lookup.
    await _ingest(authenticated_client, project_id, source_type="url", content="http://93.184.215.14/")
    doc = (await db_session.execute(select(SourceDocument).where(SourceDocument.project_id == UUID(project_id)))).scalar_one()
    assert doc.extracted_text == page_text


@pytest.mark.asyncio
async def test_rag_still_works_after_ingestion(authenticated_client, db_session):
    project_id = await _create_project(authenticated_client)
    await _ingest(authenticated_client, project_id, source_type="text", content=LONG_TEXT)
    chunks = (await db_session.execute(select(DocumentChunk).where(DocumentChunk.project_id == UUID(project_id)))).scalars().all()
    assert len(chunks) > 1
    assert all(c.embedding is not None for c in chunks)


@pytest.mark.asyncio
async def test_legacy_source_without_extracted_text_falls_back_to_chunks(db_session, test_user):
    project = Project(title="Legacy", source_type="URL", source_reference="http://example.com", user_id=test_user.id)
    db_session.add(project)
    await db_session.commit()
    doc = SourceDocument(project_id=project.id, source_type="url", name="Legacy URL", status="completed", metadata_={})
    db_session.add(doc)
    await db_session.commit()
    for index, content in enumerate(["First chunk.", "Second chunk."]):
        db_session.add(DocumentChunk(source_document_id=doc.id, project_id=project.id, chunk_index=index, content=content))
    await db_session.commit()

    assert await get_project_source_text(db_session, project) == "First chunk.\nSecond chunk."


@pytest.mark.asyncio
async def test_project_without_sources_uses_project_fields(db_session, test_user):
    project = Project(title="No source", description="Full description text", source_type="Text Idea", source_reference="short", user_id=test_user.id)
    db_session.add(project)
    await db_session.commit()
    assert await get_project_source_text(db_session, project) == "Full description text"


def test_prompt_cap_is_explicit_never_silent():
    assert cap_for_prompt("short", limit=100) == "short"
    capped = cap_for_prompt("x" * 1000, limit=100)
    assert capped.startswith("x" * 100)
    assert "Source truncated for this prompt" in capped
    assert "1,000" in capped
