"""Calendar step 9 hardening: truly concurrent writes (independent sessions racing in the isolated test database).

Exactly one write may win; the loser is refused with a reason the UI handles (lock_conflict / cancelled /
duplicate_plan), and the stored row stays consistent — never half-applied, never double-cancelled, never duplicated.
"""
import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.models.schedule import Schedule
from app.services.content_planning_service import ContentPlanningService
from tests.conftest import TestingSessionLocal
from tests.test_scheduling_eligibility import approved_post

KOLKATA_9AM = "2047-03-02T09:00:00+05:30"


async def planned_entry(client, when=KOLKATA_9AM):
    project_id, _ = await approved_post(client)
    res = await client.post(f"/api/projects/{project_id}/generated-content/schedule",
                            json={"scheduled_at": when, "timezone": "Asia/Kolkata", "platform": "LinkedIn"})
    assert res.status_code == 201, res.text
    return project_id, res.json()


async def in_own_session(user_id, action):
    """Run one write in its own session/connection; return ("ok", entry) or ("refused", status, codes)."""
    async with TestingSessionLocal() as session:
        try:
            entry = await action(ContentPlanningService(session, user_id))
            return ("ok", entry.id)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            return ("refused", exc.status_code, [r["code"] for r in detail.get("reasons", [])])


async def stored(entry_id):
    async with TestingSessionLocal() as session:
        return (await session.execute(select(Schedule).where(Schedule.id == entry_id))).scalar_one()


@pytest.mark.asyncio
async def test_concurrent_cancels_cancel_once(authenticated_client, test_user):
    user_id = test_user.id
    _, entry = await planned_entry(authenticated_client)
    sid = UUID(entry["id"])
    results = await asyncio.gather(*[in_own_session(user_id, lambda s: s.cancel(sid, lock_version=1)) for _ in range(2)])
    wins = [r for r in results if r[0] == "ok"]
    losses = [r for r in results if r[0] == "refused"]
    assert len(wins) == 1 and len(losses) == 1, results
    assert losses[0][1] == 409 and losses[0][2] in (["lock_conflict"], ["cancelled"])
    row = await stored(sid)
    assert row.status == "cancelled" and row.cancelled_at is not None and row.lock_version == 2  # applied exactly once


@pytest.mark.asyncio
async def test_reschedule_racing_cancel_applies_exactly_one(authenticated_client, test_user):
    user_id = test_user.id
    _, entry = await planned_entry(authenticated_client)
    sid = UUID(entry["id"])
    new_time = datetime.fromisoformat("2047-03-05T10:00:00+05:30")
    results = await asyncio.gather(
        in_own_session(user_id, lambda s: s.reschedule(sid, lock_version=1, scheduled_at=new_time, zone_name="Asia/Kolkata")),
        in_own_session(user_id, lambda s: s.cancel(sid, lock_version=1)),
    )
    assert sorted(r[0] for r in results) == ["ok", "refused"], results
    loser = next(r for r in results if r[0] == "refused")
    assert loser[1] == 409 and loser[2] in (["lock_conflict"], ["cancelled"])
    row = await stored(sid)
    assert row.lock_version == 2
    if results[0][0] == "ok":   # the reschedule won: still planned, at the new time
        assert row.status == "planned" and row.cancelled_at is None and row.scheduled_at == new_time
    else:                       # the cancel won: cancelled, time untouched
        assert row.status == "cancelled" and row.cancelled_at is not None
        assert row.scheduled_at == datetime.fromisoformat(KOLKATA_9AM)


@pytest.mark.asyncio
async def test_duplicate_plan_submissions_create_one_entry(authenticated_client, test_user):
    user_id = test_user.id
    project_id, _ = await approved_post(authenticated_client)
    when = datetime.fromisoformat("2047-08-01T09:00:00+05:30")
    results = await asyncio.gather(*[
        in_own_session(user_id, lambda s: s.plan(project_id, scheduled_at=when, zone_name="Asia/Kolkata", platform="LinkedIn"))
        for _ in range(3)])
    assert sorted(r[0] for r in results) == ["ok", "refused", "refused"], results
    assert all(r[1] == 409 and r[2] == ["duplicate_plan"] for r in results if r[0] == "refused")
    async with TestingSessionLocal() as session:
        active = (await session.execute(select(func.count(Schedule.id)).where(
            Schedule.project_id == project_id, Schedule.scheduled_at == when, Schedule.cancelled_at.is_(None)))).scalar()
    assert active == 1


@pytest.mark.asyncio
async def test_stale_version_after_a_concurrent_change_is_refused(authenticated_client, test_user):
    """A tab that loaded lock 1 cannot overwrite a change made meanwhile (the UI then reloads the latest state)."""
    user_id = test_user.id
    _, entry = await planned_entry(authenticated_client)
    sid = UUID(entry["id"])
    first = await in_own_session(user_id, lambda s: s.reschedule(sid, lock_version=1, notes="first", notes_set=True))
    assert first[0] == "ok"
    stale = await in_own_session(user_id, lambda s: s.reschedule(sid, lock_version=1, notes="stale", notes_set=True))
    assert stale == ("refused", 409, ["lock_conflict"])
    stale_cancel = await in_own_session(user_id, lambda s: s.cancel(sid, lock_version=1))
    assert stale_cancel == ("refused", 409, ["lock_conflict"])
    row = await stored(sid)
    assert row.notes == "first" and row.lock_version == 2 and row.status == "planned"
    assert datetime.now(timezone.utc) < row.scheduled_at  # still the original future time
