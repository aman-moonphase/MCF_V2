"""Canonical workflow stage configuration, stage uniqueness, and the Product schema."""
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.core.workflow import WORKFLOW_STAGES, stage_label
from app.models.product import Product
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from app.services.workflow_stage_service import WorkflowStageService


async def _create_project(client) -> dict:
    res = await client.post("/api/projects", json={"title": "Workflow", "source_type": "Text Idea", "source_reference": "x"})
    assert res.status_code == 201
    return res.json()


@pytest.mark.asyncio
async def test_new_project_stages_follow_the_canonical_definition(authenticated_client):
    project = await _create_project(authenticated_client)
    stages = project["stages"]
    assert [s["stage_type"] for s in stages] == [d.key for d in WORKFLOW_STAGES]
    assert [s["label"] for s in stages] == [d.label for d in WORKFLOW_STAGES]
    assert [s["order"] for s in stages] == list(range(len(WORKFLOW_STAGES)))
    assert stages[0]["status"] == "Not Started"
    assert all(s["status"] == "Locked" for s in stages[1:])


def test_labels_come_from_one_definition():
    assert stage_label("topic-angle") == "Topic & Angle"
    assert stage_label("some-future-stage") == "Some Future Stage"


@pytest.mark.asyncio
async def test_stage_order_is_canonical_not_creation_time(authenticated_client, db_session):
    project = await _create_project(authenticated_client)
    project_id = UUID(project["id"])
    # Recreate an early stage so it becomes the newest row.
    await db_session.execute(delete(WorkflowStage).where(WorkflowStage.project_id == project_id, WorkflowStage.stage_type == "content-type"))
    await db_session.commit()
    res = await authenticated_client.put(f"/api/projects/{project['id']}/stages/content-type", json={"status": "Locked"})
    assert res.status_code == 200

    fetched = (await authenticated_client.get(f"/api/projects/{project['id']}")).json()
    assert [s["stage_type"] for s in fetched["stages"]] == [d.key for d in WORKFLOW_STAGES]
    listed = (await authenticated_client.get(f"/api/projects/{project['id']}/stages")).json()
    assert [s["stage_type"] for s in listed] == [d.key for d in WORKFLOW_STAGES]


@pytest.mark.asyncio
async def test_unknown_stage_types_cannot_be_created(authenticated_client):
    project = await _create_project(authenticated_client)
    res = await authenticated_client.patch(f"/api/projects/{project['id']}/stages/not-a-stage", json={"status": "Completed"})
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_database_rejects_duplicate_stage_rows(authenticated_client, db_session):
    project = await _create_project(authenticated_client)
    db_session.add(WorkflowStage(project_id=UUID(project["id"]), stage_type="storyboard", status="Locked"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_ensure_project_stages_is_idempotent(authenticated_client, db_session, test_user):
    project = await _create_project(authenticated_client)
    project_id = UUID(project["id"])
    await db_session.execute(delete(WorkflowStage).where(WorkflowStage.project_id == project_id, WorkflowStage.stage_type == "review-approval"))
    await db_session.commit()

    service = WorkflowStageService(db_session, test_user.id)
    stages = await service.ensure_project_stages(project_id)
    stages_again = await service.ensure_project_stages(project_id)
    assert [s.stage_type for s in stages] == [d.key for d in WORKFLOW_STAGES]
    assert len(stages_again) == len(WORKFLOW_STAGES)


# ─── Product schema preparation ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_one_product_many_projects(db_session, test_user):
    product = Product(name="LedgerLeaf", description="Bookkeeping for freelance designers", user_id=test_user.id)
    db_session.add(product)
    await db_session.commit()

    for title in ("Launch campaign", "GST season campaign"):
        db_session.add(Project(title=title, source_type="Text Idea", source_reference="x", user_id=test_user.id, product_id=product.id))
    await db_session.commit()

    linked = (await db_session.execute(select(Project).where(Project.product_id == product.id))).scalars().all()
    assert len(linked) == 2

    # Deleting a product keeps its projects (product_id becomes NULL).
    await db_session.delete(product)
    await db_session.commit()
    for project in linked:
        await db_session.refresh(project)
        assert project.product_id is None


@pytest.mark.asyncio
async def test_projects_work_without_a_product(authenticated_client):
    project = await _create_project(authenticated_client)
    assert project["id"]
