"""Calendar & content planning, step 7: planning an approved post from Review Approval.

- GET /api/projects/{id}/generated-content/schedule/eligibility explains, read-only, whether the saved post can be
  planned — with the same rules (and refusal codes) the plan endpoint enforces.
- Planning never changes the approved post, its evaluations, its approval or the workflow.
Demo Mode, isolated test database; nothing is published or sent.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, select

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from tests.test_content_planning_api import _blocking_evaluation, _draft, _evaluated_unapproved, _no_evaluation, _old_evaluation, _stale, _version_moved
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_scheduling_eligibility import approved_post

NEW_YORK = ZoneInfo("America/New_York")


def eligibility_url(project_id):
    return f"/api/projects/{project_id}/generated-content/schedule/eligibility"


def plan_url(project_id):
    return f"/api/projects/{project_id}/generated-content/schedule"


@pytest.mark.asyncio
async def test_eligibility_of_an_approved_evaluated_post(authenticated_client, db_session):
    project_id, product_id = await approved_post(authenticated_client)
    res = await authenticated_client.get(eligibility_url(project_id))
    assert res.status_code == 200, res.text
    body = res.json()
    post = (await db_session.execute(select(GeneratedContent).where(GeneratedContent.project_id == project_id))).scalar_one()
    assert body["eligible"] is True and body["reasons"] == []
    assert (body["project_id"], body["product_id"], body["generated_content_id"]) == (str(project_id), str(product_id), str(post.id))
    assert (body["content_type"], body["platform"], body["content_version"]) == ("Social Post", "linkedin", 1)
    assert body["evaluation_id"] and "content_digest" not in body  # the digest stays server-side


@pytest.mark.asyncio
@pytest.mark.parametrize("make, expected", [
    (_draft, ["not_approved", "evaluation_missing"]),
    (_evaluated_unapproved, ["not_approved"]),
    (_stale, ["stale_content"]),
    (_version_moved, ["approval_outdated", "evaluation_outdated"]),
    (_no_evaluation, ["evaluation_missing"]),
    (_old_evaluation, ["evaluation_outdated"]),
    (_blocking_evaluation, ["evaluation_blocking"]),
])
async def test_eligibility_explains_the_same_refusals_as_planning(authenticated_client, db_session, make, expected):
    project_id = await make(authenticated_client, db_session)
    res = await authenticated_client.get(eligibility_url(project_id))
    assert res.status_code == 200 and res.json()["eligible"] is False
    assert [r["code"] for r in res.json()["reasons"]] == expected
    assert all(r["message"] for r in res.json()["reasons"])
    when = datetime.now(timezone.utc).astimezone(NEW_YORK) + timedelta(days=30)
    plan = await authenticated_client.post(plan_url(project_id), json={
        "scheduled_at": when.isoformat(), "timezone": "America/New_York", "platform": "LinkedIn"})
    assert plan.status_code == 409 and [r["code"] for r in plan.json()["detail"]["reasons"]] == expected  # never bypassed


@pytest.mark.asyncio
async def test_eligibility_is_owner_scoped(authenticated_client, other_client):
    theirs, _ = await approved_post(other_client)
    hidden = await authenticated_client.get(eligibility_url(theirs))
    missing = await authenticated_client.get(eligibility_url(uuid.uuid4()))
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()
    assert (await other_client.get(eligibility_url(theirs))).json()["eligible"] is True


@pytest.mark.asyncio
async def test_eligibility_check_is_read_only(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    draft_id = await _draft(authenticated_client, db_session)
    statements = []
    connection = (await db_session.connection()).sync_connection
    record = lambda conn, cursor, statement, *a: statements.append(statement.lstrip().split(None, 1)[0].upper())  # noqa: E731
    event.listen(connection, "before_cursor_execute", record)
    try:
        for pid in (project_id, draft_id, uuid.uuid4()):
            await authenticated_client.get(eligibility_url(pid))
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert statements and set(statements) <= {"SELECT"}, set(statements)


@pytest.mark.asyncio
async def test_offsets_for_the_chosen_date_across_daylight_saving(authenticated_client):
    """The client sends the zone's offset for the chosen date: New York is -04:00 in July and -05:00 in January."""
    project_id, _ = await approved_post(authenticated_client)
    summer = await authenticated_client.post(plan_url(project_id), json={
        "scheduled_at": "2027-07-06T09:00:00-04:00", "timezone": "America/New_York", "platform": "LinkedIn"})
    winter = await authenticated_client.post(plan_url(project_id), json={
        "scheduled_at": "2027-01-12T09:00:00-05:00", "timezone": "America/New_York", "platform": "LinkedIn"})
    assert summer.status_code == winter.status_code == 201, (summer.text, winter.text)
    wrong = await authenticated_client.post(plan_url(project_id), json={  # a summer offset on a winter date
        "scheduled_at": "2027-01-13T09:00:00-04:00", "timezone": "America/New_York", "platform": "LinkedIn"})
    assert wrong.status_code == 422 and [r["code"] for r in wrong.json()["detail"]["reasons"]] == ["timezone_mismatch"]


@pytest.mark.asyncio
async def test_planning_leaves_the_approved_post_its_evaluation_and_workflow_untouched(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)

    async def snapshot():
        db_session.expire_all()
        post = (await db_session.execute(select(
            GeneratedContent.id, GeneratedContent.content, GeneratedContent.validation, GeneratedContent.status,
            GeneratedContent.version, GeneratedContent.approved_version, GeneratedContent.approved_at,
            GeneratedContent.context_snapshot, GeneratedContent.updated_at).where(GeneratedContent.project_id == project_id))).one()
        evaluations = (await db_session.execute(select(
            ContentEvaluation.id, ContentEvaluation.content_version, ContentEvaluation.overall, ContentEvaluation.result,
            ContentEvaluation.created_at).where(ContentEvaluation.project_id == project_id).order_by(ContentEvaluation.created_at))).all()
        stages = (await db_session.execute(select(WorkflowStage.stage_type, WorkflowStage.status, WorkflowStage.data,
                                                  WorkflowStage.updated_at).where(WorkflowStage.project_id == project_id)
                                           .order_by(WorkflowStage.stage_type))).all()
        project = (await db_session.execute(select(Project.status, Project.current_stage, Project.updated_at)
                                            .where(Project.id == project_id))).one()
        return tuple(post), [tuple(e) for e in evaluations], [tuple(s) for s in stages], tuple(project)

    before = await snapshot()
    payload = {"scheduled_at": "2027-05-04T10:30:00+05:30", "timezone": "Asia/Kolkata", "platform": "LinkedIn", "notes": "Launch"}
    first = await authenticated_client.post(plan_url(project_id), json=payload)
    assert first.status_code == 201, first.text
    duplicate = await authenticated_client.post(plan_url(project_id), json=payload)  # e.g. a double click
    assert duplicate.status_code == 409 and [r["code"] for r in duplicate.json()["detail"]["reasons"]] == ["duplicate_plan"]
    assert first.json()["status"] == "planned" and first.json()["content_version"] == 1
    assert await snapshot() == before
    # Still eligible for another slot afterwards: planning did not consume or alter the approval.
    assert (await authenticated_client.get(eligibility_url(project_id))).json()["eligible"] is True
