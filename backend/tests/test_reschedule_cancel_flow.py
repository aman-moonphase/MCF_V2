"""Calendar & content planning, step 8: the reschedule / cancel flows the Calendar UI uses.

- Stale lock_version writes are refused (409 lock_conflict with the current version) and never overwrite.
- GET /api/schedules/{id} returns the latest state (used to refresh after a conflict).
- A plan whose post changed cannot be rescheduled (content_changed) but can still be cancelled.
- Cancelled plans are kept: hidden from the calendar by default, shown with include_cancelled.
- Neither action changes the approved post, its evaluation, approval or the workflow.
Demo Mode, isolated test database; nothing is published or sent.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from tests.test_scheduling_eligibility import approved_post

UTC = timezone.utc


def plan_url(project_id):
    return f"/api/projects/{project_id}/generated-content/schedule"


async def plan(client, project_id, when):
    res = await client.post(plan_url(project_id), json={"scheduled_at": when, "timezone": "Asia/Kolkata", "platform": "LinkedIn"})
    assert res.status_code == 201, res.text
    return res.json()


def codes(res):
    return [r["code"] for r in res.json()["detail"]["reasons"]]


async def calendar_ids(client, start, end, include_cancelled=False):
    res = await client.get("/api/schedules/calendar", params={
        "start": start.isoformat(), "end": end.isoformat(), "include_cancelled": str(include_cancelled).lower()})
    assert res.status_code == 200, res.text
    return {e["id"]: e for e in res.json()["entries"]}


@pytest.mark.asyncio
async def test_stale_versions_never_overwrite_and_latest_state_is_readable(authenticated_client):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, "2043-03-02T09:00:00+05:30")
    sid = entry["id"]

    # Tab A reschedules first (lock 1 → 2) ...
    a = await authenticated_client.patch(f"/api/schedules/{sid}", json={
        "lock_version": 1, "scheduled_at": "2043-03-03T10:00:00+05:30", "timezone": "Asia/Kolkata", "notes": "from A"})
    assert a.status_code == 200 and a.json()["lock_version"] == 2
    # ... tab B still holds lock 1: refused, told the current version, nothing overwritten.
    b = await authenticated_client.patch(f"/api/schedules/{sid}", json={
        "lock_version": 1, "scheduled_at": "2043-03-09T18:00:00+05:30", "timezone": "Asia/Kolkata", "notes": "from B"})
    assert b.status_code == 409 and codes(b) == ["lock_conflict"] and b.json()["detail"]["lock_version"] == 2
    stale_cancel = await authenticated_client.post(f"/api/schedules/{sid}/cancel", json={"lock_version": 1})
    assert stale_cancel.status_code == 409 and codes(stale_cancel) == ["lock_conflict"]

    latest = (await authenticated_client.get(f"/api/schedules/{sid}")).json()  # what the UI reloads
    assert latest["lock_version"] == 2 and latest["notes"] == "from A" and latest["status"] == "planned"
    assert datetime.fromisoformat(latest["scheduled_at"].replace("Z", "+00:00")) == datetime(2043, 3, 3, 4, 30, tzinfo=UTC)

    # With the reloaded version the user's action goes through.
    ok = await authenticated_client.post(f"/api/schedules/{sid}/cancel", json={"lock_version": latest["lock_version"]})
    assert ok.status_code == 200 and ok.json()["status"] == "cancelled" and ok.json()["lock_version"] == 3


@pytest.mark.asyncio
async def test_notes_only_change_and_calendar_refresh(authenticated_client):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, "2044-05-04T10:30:00+05:30")
    notes = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 1, "notes": "Webinar first"})
    assert notes.status_code == 200 and notes.json()["notes"] == "Webinar first" and notes.json()["scheduled_at"] == entry["scheduled_at"]
    cleared = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 2, "notes": None})
    assert cleared.status_code == 200 and cleared.json()["notes"] is None

    moved = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={
        "lock_version": 3, "scheduled_at": "2044-05-06T08:00:00+05:30", "timezone": "Asia/Kolkata"})
    assert moved.status_code == 200
    day = lambda d: (datetime(2044, 5, d, tzinfo=UTC) - timedelta(hours=5, minutes=30), datetime(2044, 5, d + 1, tzinfo=UTC) - timedelta(hours=5, minutes=30))  # noqa: E731
    assert entry["id"] not in await calendar_ids(authenticated_client, *day(4))
    on_new_day = await calendar_ids(authenticated_client, *day(6))
    assert on_new_day[entry["id"]]["conditions"] == [] and on_new_day[entry["id"]]["lock_version"] == 4


@pytest.mark.asyncio
async def test_changed_post_cannot_be_rescheduled_but_can_be_cancelled(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, "2045-07-01T09:00:00+05:30")
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id)
                             .values(content={"hook": "Changed after planning"}))
    await db_session.commit()
    window = (datetime(2045, 6, 30, tzinfo=UTC), datetime(2045, 7, 2, tzinfo=UTC))
    assert (await calendar_ids(authenticated_client, *window))[entry["id"]]["conditions"] == ["post_changed"]

    refused = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={
        "lock_version": 1, "scheduled_at": "2045-07-02T09:00:00+05:30", "timezone": "Asia/Kolkata"})
    assert refused.status_code == 409 and codes(refused) == ["content_changed"]
    cancelled = await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel", json={"lock_version": 1})
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled" and cancelled.json()["cancelled_at"]

    # Hidden by default, kept in history and shown with include_cancelled (stored status, not a condition).
    assert entry["id"] not in await calendar_ids(authenticated_client, *window)
    kept = (await calendar_ids(authenticated_client, *window, include_cancelled=True))[entry["id"]]
    assert kept["status"] == "cancelled" and kept["cancelled_at"] and kept["content_version"] == entry["content_version"]
    assert kept["generated_content_id"] == entry["generated_content_id"] and "published" not in str(kept).lower()
    again = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 2, "notes": "x"})
    assert again.status_code == 409 and codes(again) == ["cancelled"]


@pytest.mark.asyncio
async def test_reschedule_and_cancel_leave_post_evaluation_approval_and_workflow_untouched(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, "2046-01-10T09:00:00+05:30")

    async def snapshot():
        db_session.expire_all()
        post = (await db_session.execute(select(
            GeneratedContent.content, GeneratedContent.status, GeneratedContent.version, GeneratedContent.approved_version,
            GeneratedContent.approved_at, GeneratedContent.updated_at).where(GeneratedContent.project_id == project_id))).one()
        evaluations = (await db_session.execute(select(ContentEvaluation.id, ContentEvaluation.content_version, ContentEvaluation.result)
                                                .where(ContentEvaluation.project_id == project_id))).all()
        stages = (await db_session.execute(select(WorkflowStage.stage_type, WorkflowStage.status, WorkflowStage.data, WorkflowStage.updated_at)
                                           .where(WorkflowStage.project_id == project_id).order_by(WorkflowStage.stage_type))).all()
        project = (await db_session.execute(select(Project.status, Project.current_stage).where(Project.id == project_id))).one()
        return tuple(post), [tuple(e) for e in evaluations], [tuple(s) for s in stages], tuple(project)

    before = await snapshot()
    moved = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={
        "lock_version": 1, "scheduled_at": "2046-01-11T09:00:00+05:30", "timezone": "Asia/Kolkata", "notes": "moved"})
    assert moved.status_code == 200
    assert (await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel", json={"lock_version": 2})).status_code == 200
    assert await snapshot() == before
