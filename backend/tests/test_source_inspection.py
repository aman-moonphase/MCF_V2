import uuid
import pytest
from sqlalchemy import select
from app.models.source import SourceDocument
from tests.test_promotion_strategy import other_client  # noqa: F401

LONG_CONTENT = (
    "BudgetBloom is a personal budgeting tool designed for young professionals and college students. "
    "It helps users categorize expenses, track monthly savings, and avoid impulse spending. "
    "All figures must be based on actual verified receipts and account statements."
)


async def _create_project(client, reference: str = "BudgetBloom Reference") -> str:
    res = await client.post(
        "/api/projects",
        json={"title": "Inspection Test Project", "source_type": "Text Idea", "source_reference": reference},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _ingest_text(client, project_id: str, text: str) -> dict:
    res = await client.post(
        f"/api/projects/{project_id}/sources/ingest",
        data={"source_type": "text", "content": text},
    )
    assert res.status_code == 200, res.text
    return res.json()


@pytest.mark.asyncio
async def test_get_project_sources_returns_full_stored_content_and_metadata(authenticated_client):
    project_id = await _create_project(authenticated_client, "BudgetBloom text idea")
    ingest_res = await _ingest_text(authenticated_client, project_id, LONG_CONTENT)
    source_id = ingest_res["id"]

    # Retrieve all sources for project
    res = await authenticated_client.get(f"/api/projects/{project_id}/sources")
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["project_id"] == project_id
    assert data["project_title"] == "Inspection Test Project"
    assert data["project_source_type"] == "Text Idea"
    assert data["project_source_reference"] == "BudgetBloom text idea"
    assert len(data["sources"]) == 1

    source = data["sources"][0]
    assert source["id"] == source_id
    assert source["source_type"] == "text"
    assert source["status"] == "completed"
    assert source["extracted_text"] == LONG_CONTENT
    assert source["char_count"] == len(LONG_CONTENT)
    assert source["chunk_count"] >= 1
    assert source["embedding_provider"] == "demo"

    # Retrieve single source detail
    detail_res = await authenticated_client.get(f"/api/projects/{project_id}/sources/{source_id}")
    assert detail_res.status_code == 200, detail_res.text
    detail = detail_res.json()
    assert detail["id"] == source_id
    assert detail["extracted_text"] == LONG_CONTENT
    assert detail["status"] == "completed"


@pytest.mark.asyncio
async def test_source_inspection_enforces_user_isolation(authenticated_client, other_client):
    project_id = await _create_project(authenticated_client, "Confidential Project")
    ingest_res = await _ingest_text(authenticated_client, project_id, "Secret financial roadmap.")
    source_id = ingest_res["id"]

    # Other user cannot access the project sources list
    other_list_res = await other_client.get(f"/api/projects/{project_id}/sources")
    assert other_list_res.status_code == 404

    # Other user cannot access the source detail
    other_detail_res = await other_client.get(f"/api/projects/{project_id}/sources/{source_id}")
    assert other_detail_res.status_code == 404


@pytest.mark.asyncio
async def test_missing_and_invalid_source_inspection_handling(authenticated_client):
    # Project with no ingested sources
    project_id = await _create_project(authenticated_client, "Un-ingested draft reference")
    res = await authenticated_client.get(f"/api/projects/{project_id}/sources")
    assert res.status_code == 200
    data = res.json()
    assert data["sources"] == []
    assert data["project_source_reference"] == "Un-ingested draft reference"

    # Non-existent source UUID returns 404
    fake_source_id = str(uuid.uuid4())
    res_missing = await authenticated_client.get(f"/api/projects/{project_id}/sources/{fake_source_id}")
    assert res_missing.status_code == 404

    # Invalid UUID format returns 422
    res_bad_uuid = await authenticated_client.get(f"/api/projects/{project_id}/sources/not-a-uuid")
    assert res_bad_uuid.status_code == 422

    res_bad_project = await authenticated_client.get("/api/projects/not-a-project-uuid/sources")
    assert res_bad_project.status_code == 422
