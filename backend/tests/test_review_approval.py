"""Review Approval (product workflow): a human approves the SAVED generated post.

Regression: the stage showed a placeholder and its generic "Approve & Continue" completed the workflow without any
content being approved. Approval must load the saved post, approve only the current saved version, refuse missing
or stale content, persist the decision, and never publish, schedule or send anything.
"""
from uuid import UUID

import pytest
import requests
from sqlalchemy import func, select

from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.workflow_stage import WorkflowStage
from tests.test_generate_content import approve_type, gen_url, generate, ready_project
from tests.test_promotion_strategy import approve as approve_strategy
from tests.test_promotion_strategy import generate as generate_strategy
from tests.test_promotion_strategy import other_client  # noqa: F401


async def evaluate(client, project_id, version):
    """Evaluate & Improve now precedes Review Approval: approval needs an evaluation of the current version."""
    res = await client.post(f"/api/projects/{project_id}/evaluation", json={"version": version})
    assert res.status_code == 200, res.text
    return res.json()


def approve_url(project_id):
    return f"{gen_url(project_id)}/approve"


async def stage_status(client, project_id, stage_type, status):
    return await client.patch(f"/api/projects/{project_id}/stages/{stage_type}", json={"status": status})


@pytest.mark.asyncio
async def test_review_loads_the_saved_post_including_manual_edits(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    first = await generate(authenticated_client, project_id)
    saved = await authenticated_client.patch(gen_url(project_id), json={"cta": "Message us to try LedgerLeaf.", "version": 1})
    assert saved.status_code == 200, saved.text

    state = (await authenticated_client.get(gen_url(project_id))).json()
    draft = state["draft"]
    assert draft["version"] == 2 and draft["edited"] is True and draft["status"] == "draft"
    assert draft["content"]["cta"] == "Message us to try LedgerLeaf."
    assert draft["content"]["hook"] == first["draft"]["content"]["hook"]
    assert draft["approved_version"] is None and draft["approved_at"] is None
    assert draft["is_demo"] is True and draft["evidence"] and draft["validation"]["character_count"] > 0
    assert state["policy"]["platform"] == "LinkedIn" and state["policy"]["content_type"] == "Social Post"


@pytest.mark.asyncio
async def test_approving_the_current_saved_version_persists(authenticated_client, db_session):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await evaluate(authenticated_client, project_id, 1)
    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["status"] == "approved" and state["can_generate"] is False
    assert state["draft"]["status"] == "approved" and state["draft"]["approved_version"] == 1 and state["draft"]["approved_at"]

    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as fresh:
        row = (await fresh.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalar_one()
        assert row.status == "approved" and row.approved_version == row.version == 1 and row.approved_at is not None
        stage = (await fresh.execute(select(WorkflowStage).where(WorkflowStage.project_id == UUID(project_id),
                                                                  WorkflowStage.stage_type == "review-approval"))).scalar_one()
        assert stage.data["approved_version"] == 1 and stage.data["generated_content_id"] == str(row.id)

    # The approved version is frozen: no edits, no regeneration, no second approval.
    assert (await authenticated_client.patch(gen_url(project_id), json={"cta": "Changed.", "version": 1})).status_code == 409
    assert (await authenticated_client.post(gen_url(project_id), json={})).status_code == 409
    again = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert again.status_code == 409 and "already approved" in again.json()["detail"]


@pytest.mark.asyncio
async def test_only_the_version_the_reviewer_saw_can_be_approved(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.patch(gen_url(project_id), json={"cta": "Message us to try LedgerLeaf.", "version": 1})
    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})  # reviewer saw v1, saved is v2
    assert res.status_code == 409 and "changed since you opened it" in res.json()["detail"]
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"]["status"] == "draft"


@pytest.mark.asyncio
async def test_missing_content_cannot_be_approved(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert res.status_code == 409 and "no saved post" in res.json()["detail"]


@pytest.mark.asyncio
async def test_stale_content_cannot_be_approved(authenticated_client):
    project_id, product_id, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    # The strategy is regenerated and re-approved (and the Content Type re-confirmed): the post is now stale.
    s = await generate_strategy(authenticated_client, product_id)
    await approve_strategy(authenticated_client, project_id, product_id, s["version"])
    await approve_type(authenticated_client, project_id)
    state = (await authenticated_client.get(gen_url(project_id))).json()
    assert state["stale"] is True
    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert res.status_code == 409 and "stale" in res.json()["detail"] and "Promotion Strategy" in res.json()["detail"]


@pytest.mark.asyncio
async def test_unapproved_prerequisites_block_approval(authenticated_client):
    project_id, product_id, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.patch(f"/api/products/{product_id}/profile", json={"profile": {"target_audience": "Wedding photographers"}})
    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert res.status_code == 409 and "Product Profile" in res.json()["detail"]


@pytest.mark.asyncio
async def test_review_stage_completes_only_after_the_post_is_approved(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    refused = await stage_status(authenticated_client, project_id, "review-approval", "Completed")
    assert refused.status_code == 409 and "Approve the saved post" in refused.json()["detail"]
    entering = await stage_status(authenticated_client, project_id, "review-approval", "In Progress")
    assert entering.status_code == 409 and "Evaluate & Improve" in entering.json()["detail"]  # evaluation comes first
    await evaluate(authenticated_client, project_id, 1)
    assert (await stage_status(authenticated_client, project_id, "review-approval", "In Progress")).status_code == 200

    await authenticated_client.post(approve_url(project_id), json={"version": 1})
    done = await stage_status(authenticated_client, project_id, "review-approval", "Completed")
    assert done.status_code == 200 and done.json()["status"] == "Completed"


@pytest.mark.asyncio
async def test_other_users_cannot_review_or_approve(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    assert (await other_client.get(gen_url(project_id))).status_code == 404
    assert (await other_client.post(approve_url(project_id), json={"version": 1})).status_code == 404
    assert (await authenticated_client.get(gen_url(project_id))).json()["draft"]["status"] == "draft"


@pytest.mark.asyncio
async def test_legacy_projects_keep_their_generic_review_step(authenticated_client, db_session, test_user):
    project = Project(title="Legacy", source_type="Text Idea", source_reference="x", user_id=test_user.id)
    db_session.add(project)
    await db_session.commit()
    for key in ("source-grounding", "content-type", "final-script", "review-approval"):
        db_session.add(WorkflowStage(project_id=project.id, stage_type=key, status="Locked"))
    await db_session.commit()
    assert (await stage_status(authenticated_client, project.id, "review-approval", "Completed")).status_code == 200
    assert (await authenticated_client.post(approve_url(project.id), json={"version": 1})).status_code == 409


@pytest.mark.asyncio
async def test_approval_never_publishes_schedules_or_sends(authenticated_client, db_session, smtp_outbox, monkeypatch):
    calls = []

    def no_network(self, method, url, *args, **kwargs):
        calls.append((method, url))
        raise AssertionError(f"Approval must not make outbound requests: {method} {url}")

    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await evaluate(authenticated_client, project_id, 1)
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    before = (await db_session.execute(select(func.count(Schedule.id)))).scalar()

    res = await authenticated_client.post(approve_url(project_id), json={"version": 1})
    assert res.status_code == 200, res.text
    await stage_status(authenticated_client, project_id, "review-approval", "Completed")

    assert calls == [] and smtp_outbox == []
    assert (await db_session.execute(select(func.count(Schedule.id)))).scalar() == before
    assert (await db_session.execute(select(func.count(Schedule.id)).where(Schedule.project_id == UUID(project_id)))).scalar() == 0
    assert res.json()["draft"]["status"] == "approved"  # approved, not "published"/"scheduled"
