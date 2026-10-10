"""Calendar & content planning, step 3: planning endpoints and constrained legacy schedule routes.

Planning only — nothing is published, posted, queued or sent. Posts come from the real workflow in Demo Mode
(generate → evaluate → approve); conditions are then broken in the isolated test database only.
"""
import uuid
from datetime import datetime, timedelta, timezone
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import delete, func, select, update

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.workflow_stage import WorkflowStage
from app.services.scheduling_eligibility import content_digest
from tests.test_generate_content import approve_type, gen_url, generate, ready_project
from tests.test_promotion_strategy import approve as approve_strategy
from tests.test_promotion_strategy import generate as generate_strategy
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_review_approval import evaluate
from tests.test_scheduling_eligibility import approved_post

IST = ZoneInfo("Asia/Kolkata")
LONDON = ZoneInfo("Europe/London")
WHEN = datetime(2027, 3, 2, 9, 0, tzinfo=IST)  # comfortably in the future


def plan_url(project_id):
    return f"/api/projects/{project_id}/generated-content/schedule"


def body(when=WHEN, zone="Asia/Kolkata", platform="LinkedIn", **extra):
    return {"scheduled_at": when if isinstance(when, str) else when.isoformat(), "timezone": zone, "platform": platform, **extra}


def instant(value: str) -> datetime:
    """Parse an API timestamp (Python 3.10's fromisoformat does not accept a trailing "Z")."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def codes(res):
    return [r["code"] for r in res.json()["detail"]["reasons"]]


async def plan(client, project_id, **kwargs):
    res = await client.post(plan_url(project_id), json=body(**kwargs))
    assert res.status_code == 201, res.text
    return res.json()


async def count_schedules(db, project_id=None):
    stmt = select(func.count(Schedule.id))
    if project_id is not None:
        stmt = stmt.where(Schedule.project_id == project_id)
    db.expire_all()
    return (await db.execute(stmt)).scalar()


# ─── Create ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_plan_an_approved_currently_evaluated_post(authenticated_client, db_session):
    project_id, product_id = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, notes="Launch week", platform="linkedin", product_id=str(product_id))
    db_session.expire_all()
    post = (await db_session.execute(select(GeneratedContent).where(GeneratedContent.project_id == project_id))).scalar_one()
    assert entry["status"] == "planned" and entry["platform"] == "LinkedIn" and entry["lock_version"] == 1
    assert (entry["project_id"], entry["product_id"], entry["generated_content_id"]) == (str(project_id), str(product_id), str(post.id))
    assert entry["content_version"] == 1 and entry["content_type"] == "Social Post"
    assert entry["content_digest"] == content_digest(post.content) and len(entry["content_digest"]) == 64
    assert entry["timezone"] == "Asia/Kolkata" and entry["notes"] == "Launch week" and entry["cancelled_at"] is None
    assert instant(entry["scheduled_at"]) == WHEN  # the same instant (03:30 UTC)

    listed = (await authenticated_client.get("/api/schedules")).json()
    assert any(e["id"] == entry["id"] and e["status"] == "planned" for e in listed)
    assert post.status == "approved" and post.version == post.approved_version == 1  # the post is untouched


@pytest.mark.asyncio
async def test_status_cannot_be_supplied_when_planning(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    for status_ in ("Published", "Completed", "planned"):
        res = await authenticated_client.post(plan_url(project_id), json=body(status=status_))
        assert res.status_code == 422, res.text
    assert await count_schedules(db_session, project_id) == 0


async def _draft(client, db):
    project_id, _, _ = await ready_project(client)
    await generate(client, project_id)
    return UUID(project_id)


async def _evaluated_unapproved(client, db):
    project_id, _, _ = await ready_project(client)
    await generate(client, project_id)
    await evaluate(client, project_id, 1)
    return UUID(project_id)


async def _stale(client, db):
    project_id, product_id = await approved_post(client)
    s = await generate_strategy(client, str(product_id))
    await approve_strategy(client, str(project_id), str(product_id), s["version"])
    await approve_type(client, str(project_id))
    return project_id


async def _version_moved(client, db):
    project_id, _ = await approved_post(client)
    await db.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id).values(version=2))
    await db.commit()
    return project_id


async def _no_evaluation(client, db):
    project_id, _ = await approved_post(client)
    await db.execute(delete(ContentEvaluation).where(ContentEvaluation.project_id == project_id))
    await db.commit()
    return project_id


async def _old_evaluation(client, db):
    project_id, _ = await approved_post(client)
    await db.execute(update(ContentEvaluation).where(ContentEvaluation.project_id == project_id).values(content_version=0))
    await db.commit()
    return project_id


async def _blocking_evaluation(client, db):
    project_id, _ = await approved_post(client)
    await db.execute(update(ContentEvaluation).where(ContentEvaluation.project_id == project_id).values(overall="not_ready"))
    await db.commit()
    return project_id


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
async def test_ineligible_posts_are_refused_with_reasons(authenticated_client, db_session, make, expected):
    project_id = await make(authenticated_client, db_session)
    res = await authenticated_client.post(plan_url(project_id), json=body())
    assert res.status_code == 409, res.text
    assert codes(res) == expected and res.json()["detail"]["message"] == "This post cannot be planned."
    assert all(r["message"] for r in res.json()["detail"]["reasons"])
    assert await count_schedules(db_session, project_id) == 0


@pytest.mark.asyncio
async def test_other_users_projects_and_wrong_product(authenticated_client, other_client, db_session):
    theirs, their_product = await approved_post(other_client)
    res = await authenticated_client.post(plan_url(theirs), json=body(product_id=str(their_product)))
    missing = await authenticated_client.post(plan_url(uuid.uuid4()), json=body())
    assert res.status_code == missing.status_code == 404 and res.json() == missing.json()  # nothing about theirs
    assert codes(res) == ["project_not_found"] and str(theirs) not in res.text and str(their_product) not in res.text
    assert await count_schedules(db_session, theirs) == 0

    mine, _ = await approved_post(authenticated_client)
    wrong = await authenticated_client.post(plan_url(mine), json=body(product_id=str(their_product)))
    assert wrong.status_code == 409 and codes(wrong) == ["product_mismatch"]


@pytest.mark.asyncio
async def test_only_linkedin_social_posts_can_be_planned(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    for platform in ("Twitter", "Instagram", "YouTube", ""):
        res = await authenticated_client.post(plan_url(project_id), json=body(platform=platform))
        assert res.status_code == 422, res.text
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id).values(content_type="Short Video"))
    await db_session.commit()
    res = await authenticated_client.post(plan_url(project_id), json=body())
    assert res.status_code == 409 and codes(res) == ["unsupported_content"]
    assert await count_schedules(db_session, project_id) == 0


# ─── Time zones ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_time_and_zone_validation(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    cases = [
        (body(zone="Mars/Olympus_Mons"), ["invalid_timezone"]),
        (body(zone="IST"), ["invalid_timezone"]),
        (body(zone=" Asia/Kolkata"), ["invalid_timezone"]),
        (body(when="2027-03-02T09:00:00"), ["timezone_required"]),  # no offset: never guess from the server clock
        (body(when=datetime.now(IST) - timedelta(minutes=5)), ["time_in_past"]),
        # The offset must be the zone's offset at that instant (09:00+00:00 is not a Kolkata time).
        (body(when="2027-03-02T09:00:00+00:00"), ["timezone_mismatch"]),
    ]
    for payload, expected in cases:
        res = await authenticated_client.post(plan_url(project_id), json=payload)
        assert res.status_code == 422, (payload, res.text)
        assert codes(res) == expected, (payload, res.json())
    assert await count_schedules(db_session, project_id) == 0


@pytest.mark.asyncio
async def test_daylight_saving_transitions(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    # Spring forward (London, 28 Mar 2027 01:00 → 02:00): 01:30 local does not exist under either offset.
    for gap in ("2027-03-28T01:30:00+00:00", "2027-03-28T01:30:00+01:00"):
        res = await authenticated_client.post(plan_url(project_id), json=body(when=gap, zone="Europe/London"))
        assert res.status_code == 422 and codes(res) == ["timezone_mismatch"], res.text
    after_gap = await plan(authenticated_client, project_id, when="2027-03-28T03:00:00+01:00", zone="Europe/London")
    assert instant(after_gap["scheduled_at"]) == datetime(2027, 3, 28, 2, 0, tzinfo=timezone.utc)

    # Fall back (31 Oct 2027 02:00 → 01:00): 01:30 happens twice; each explicit offset is its own instant.
    first = await plan(authenticated_client, project_id, when="2027-10-31T01:30:00+01:00", zone="Europe/London")
    second = await plan(authenticated_client, project_id, when="2027-10-31T01:30:00+00:00", zone="Europe/London")
    a, b = (instant(e["scheduled_at"]) for e in (first, second))
    assert b - a == timedelta(hours=1)
    assert a.astimezone(LONDON).strftime("%H:%M %Z") == "01:30 BST" and b.astimezone(LONDON).strftime("%H:%M %Z") == "01:30 GMT"
    assert {first["timezone"], second["timezone"]} == {"Europe/London"}


# ─── Duplicates and cancellation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_duplicate_active_plans_and_replacement_after_cancel(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    first = await plan(authenticated_client, project_id)
    dup = await authenticated_client.post(plan_url(project_id), json=body())
    assert dup.status_code == 409 and codes(dup) == ["duplicate_plan"]
    # The same instant written in another zone is still the same slot.
    dup_utc = await authenticated_client.post(plan_url(project_id), json=body(when=WHEN.astimezone(timezone.utc), zone="UTC"))
    assert dup_utc.status_code == 409 and codes(dup_utc) == ["duplicate_plan"]

    cancelled = await authenticated_client.post(f"/api/schedules/{first['id']}/cancel", json={"lock_version": 1})
    assert cancelled.status_code == 200, cancelled.text
    replacement = await plan(authenticated_client, project_id)
    assert replacement["id"] != first["id"]
    assert await count_schedules(db_session, project_id) == 2  # the cancelled plan is kept


@pytest.mark.asyncio
async def test_cancellation_keeps_the_entry_and_its_history(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id, notes="Keep me")
    stale = await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel", json={"lock_version": 7})
    assert stale.status_code == 409 and codes(stale) == ["lock_conflict"] and stale.json()["detail"]["lock_version"] == 1

    res = await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel")
    assert res.status_code == 200, res.text
    done = res.json()
    assert done["status"] == "cancelled" and done["cancelled_at"] and done["lock_version"] == 2
    for key in ("project_id", "product_id", "generated_content_id", "content_version", "content_digest", "content_type",
                "timezone", "notes", "platform", "scheduled_at", "created_at"):
        assert done[key] == entry[key], key

    again = await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel")
    assert again.status_code == 409 and codes(again) == ["cancelled"]
    moved = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 2, "notes": "x"})
    assert moved.status_code == 409 and codes(moved) == ["cancelled"]
    # Cancelled entries are off the calendar by default, but kept and readable.
    assert all(e["id"] != entry["id"] for e in (await authenticated_client.get("/api/schedules")).json())
    kept = (await authenticated_client.get("/api/schedules", params={"include_cancelled": True})).json()
    assert any(e["id"] == entry["id"] and e["status"] == "cancelled" for e in kept)
    assert (await authenticated_client.get(f"/api/schedules/{entry['id']}")).json()["status"] == "cancelled"
    # Planned entries are never deleted or edited through the legacy routes.
    assert (await authenticated_client.delete(f"/api/schedules/{entry['id']}")).status_code == 409
    assert (await authenticated_client.put(f"/api/schedules/{entry['id']}", json={"status": "Scheduled"})).status_code == 409
    assert await count_schedules(db_session, project_id) == 1


# ─── Rescheduling ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reschedule_with_lock_version(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id)
    later = WHEN + timedelta(days=1, hours=2)
    res = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={
        "lock_version": 1, "scheduled_at": later.isoformat(), "notes": "Moved to Wednesday"})
    assert res.status_code == 200, res.text
    moved = res.json()
    assert moved["lock_version"] == 2 and instant(moved["scheduled_at"]) == later
    assert moved["notes"] == "Moved to Wednesday" and moved["status"] == "planned"
    assert (moved["content_version"], moved["content_digest"]) == (entry["content_version"], entry["content_digest"])

    stale = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 1, "notes": "late"})
    assert stale.status_code == 409 and codes(stale) == ["lock_conflict"] and stale.json()["detail"]["lock_version"] == 2

    # Only planning fields: status / content fields are not accepted.
    for field, value in (("status", "Published"), ("content_version", 9), ("generated_content_id", str(uuid.uuid4()))):
        bad = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 2, field: value})
        assert bad.status_code == 422, (field, bad.text)

    # Change the zone label only: the instant is kept.
    relabelled = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 2, "timezone": "Europe/London"})
    assert relabelled.status_code == 200 and relabelled.json()["timezone"] == "Europe/London"
    assert relabelled.json()["scheduled_at"] == moved["scheduled_at"] and relabelled.json()["lock_version"] == 3

    for payload, status_, expected in (
        ({"scheduled_at": "2027-03-04T09:00:00"}, 422, ["timezone_required"]),
        ({"scheduled_at": (datetime.now(LONDON) - timedelta(hours=1)).isoformat()}, 422, ["time_in_past"]),  # zone is London now
        ({"timezone": "Not/AZone"}, 422, ["invalid_timezone"]),
        ({"platform": "Twitter"}, 422, ["unsupported_platform"]),
        ({"scheduled_at": "2027-03-28T01:30:00+00:00"}, 422, ["timezone_mismatch"]),  # London DST gap
    ):
        bad = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 3, **payload})
        assert bad.status_code == status_ and codes(bad) == expected, (payload, bad.text)
    db_session.expire_all()
    row = (await db_session.execute(select(Schedule).where(Schedule.id == UUID(entry["id"])))).scalar_one()
    assert row.lock_version == 3  # refused changes left the entry alone


@pytest.mark.asyncio
async def test_reschedule_rechecks_the_post(authenticated_client, db_session):
    project_id, _ = await approved_post(authenticated_client)
    entry = await plan(authenticated_client, project_id)
    other = await plan(authenticated_client, project_id, when=WHEN + timedelta(hours=1))
    clash = await authenticated_client.patch(f"/api/schedules/{other['id']}", json={"lock_version": 1, "scheduled_at": WHEN.isoformat()})
    assert clash.status_code == 409 and codes(clash) == ["duplicate_plan"]

    # The approved post's saved content no longer matches what was planned.
    await db_session.execute(update(GeneratedContent).where(GeneratedContent.project_id == project_id)
                             .values(content={"hook": "Changed behind the plan's back"}))
    await db_session.commit()
    res = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 1, "notes": "x"})
    assert res.status_code == 409 and codes(res) == ["content_changed"]

    # The evaluation goes away: eligibility is checked again on every reschedule.
    await db_session.execute(delete(ContentEvaluation).where(ContentEvaluation.project_id == project_id))
    await db_session.commit()
    res = await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 1, "notes": "x"})
    assert res.status_code == 409 and "evaluation_missing" in codes(res)


@pytest.mark.asyncio
async def test_other_users_entries_are_not_found(authenticated_client, other_client):
    project_id, _ = await approved_post(other_client)
    theirs = await plan(other_client, project_id)
    for res in (await authenticated_client.patch(f"/api/schedules/{theirs['id']}", json={"lock_version": 1, "notes": "x"}),
                await authenticated_client.post(f"/api/schedules/{theirs['id']}/cancel"),
                await authenticated_client.get(f"/api/schedules/{theirs['id']}"),
                await authenticated_client.put(f"/api/schedules/{theirs['id']}", json={"platform": "LinkedIn"}),
                await authenticated_client.delete(f"/api/schedules/{theirs['id']}")):
        assert res.status_code == 404 and "planned" not in res.text
    assert (await other_client.get(f"/api/schedules/{theirs['id']}")).json()["status"] == "planned"


# ─── Legacy routes ──────────────────────────────────────────────────────────

async def legacy_entry(db, user_id, status_="Scheduled"):
    """A legacy-style project with a completed script, and a legacy entry (no post reference)."""
    project = Project(title="Legacy calendar project", source_type="Text Idea", source_reference="x", user_id=user_id)
    db.add(project)
    await db.flush()
    db.add(WorkflowStage(project_id=project.id, stage_type="final-script", status="Completed", data={"script": "x"}))
    entry = Schedule(project_id=project.id, platform="LinkedIn", status=status_,
                     scheduled_at=datetime(2026, 9, 29, 21, 35, tzinfo=timezone.utc))  # in the past, like the real ones
    db.add(entry)
    await db.commit()
    return project.id, entry.id


@pytest.mark.asyncio
async def test_legacy_entries_stay_readable_and_cannot_bypass_planning(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project_id, entry_id = await legacy_entry(db_session, user_id)
    listed = (await authenticated_client.get("/api/schedules")).json()
    legacy = next(e for e in listed if e["id"] == str(entry_id))
    assert legacy["status"] == "Scheduled" and legacy["generated_content_id"] is None and legacy["content_version"] is None
    assert legacy["lock_version"] == 1 and legacy["project_title"] == "Legacy calendar project"
    assert (await authenticated_client.get(f"/api/schedules/{entry_id}")).status_code == 200

    for status_ in ("Published", "published", "Completed", "completed", "planned", "cancelled", "Approved"):
        res = await authenticated_client.put(f"/api/schedules/{entry_id}", json={"status": status_})
        assert res.status_code == 422, (status_, res.text)
    naive = await authenticated_client.put(f"/api/schedules/{entry_id}", json={"scheduled_at": "2026-12-01T09:00:00"})
    assert naive.status_code == 422
    # What the existing calendar dialog sends still works: platform/time plus the unchanged status.
    ok = await authenticated_client.put(f"/api/schedules/{entry_id}", json={
        "platform": "LinkedIn", "scheduled_at": "2026-12-01T03:30:00Z", "status": "Scheduled"})
    assert ok.status_code == 200 and ok.json()["status"] == "Scheduled"

    # The new planning paths refuse legacy entries; nothing is invented for them.
    assert codes(await authenticated_client.patch(f"/api/schedules/{entry_id}", json={"lock_version": 2, "notes": "x"})) == ["legacy_entry"]
    assert codes(await authenticated_client.post(f"/api/schedules/{entry_id}/cancel")) == ["legacy_entry"]
    db_session.expire_all()
    row = (await db_session.execute(select(Schedule).where(Schedule.id == entry_id))).scalar_one()
    assert (row.status, row.generated_content_id, row.product_id, row.content_version) == ("Scheduled", None, None, None)

    # Legacy creation cannot pick a status either; DELETE still works for legacy entries.
    for status_ in ("Published", "Completed", "planned"):
        res = await authenticated_client.post("/api/schedules", json={
            "project_id": str(project_id), "platform": "LinkedIn", "scheduled_at": "2026-12-02T03:30:00Z", "status": status_})
        assert res.status_code == 422, res.text
    created = await authenticated_client.post("/api/schedules", json={
        "project_id": str(project_id), "platform": "LinkedIn", "scheduled_at": "2026-12-02T03:30:00Z"})
    assert created.status_code == 200 and created.json()["status"] == "Scheduled"
    assert (await authenticated_client.delete(f"/api/schedules/{entry_id}")).status_code == 204


@pytest.mark.asyncio
async def test_legacy_entry_with_an_existing_odd_status_keeps_it(authenticated_client, db_session, test_user):
    user_id = test_user.id
    _, entry_id = await legacy_entry(db_session, user_id, status_="Draft")
    res = await authenticated_client.put(f"/api/schedules/{entry_id}", json={"platform": "LinkedIn", "status": "Draft"})
    assert res.status_code == 200 and res.json()["status"] == "Draft"  # unchanged value is accepted, never relabelled


# ─── Planning never publishes or touches the post ───────────────────────────

@pytest.mark.asyncio
async def test_planning_never_publishes_or_changes_the_post(authenticated_client, db_session, smtp_outbox, monkeypatch):
    import requests
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("planning must not make network calls")

    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    project_id, _ = await approved_post(authenticated_client)

    async def state():
        db_session.expire_all()
        post = (await db_session.execute(select(GeneratedContent.status, GeneratedContent.version, GeneratedContent.approved_version,
                                                GeneratedContent.approved_at, GeneratedContent.content, GeneratedContent.updated_at)
                                         .where(GeneratedContent.project_id == project_id))).one()
        stages = (await db_session.execute(select(WorkflowStage.stage_type, WorkflowStage.status, WorkflowStage.updated_at)
                                           .where(WorkflowStage.project_id == project_id).order_by(WorkflowStage.stage_type))).all()
        project = (await db_session.execute(select(Project.status, Project.current_stage).where(Project.id == project_id))).one()
        evaluations = (await db_session.execute(select(func.count(ContentEvaluation.id)).where(ContentEvaluation.project_id == project_id))).scalar()
        return tuple(post), [tuple(s) for s in stages], tuple(project), evaluations

    before = await state()
    entry = await plan(authenticated_client, project_id)
    await authenticated_client.patch(f"/api/schedules/{entry['id']}", json={"lock_version": 1, "notes": "n"})
    await authenticated_client.post(f"/api/schedules/{entry['id']}/cancel")
    assert await state() == before
    assert smtp_outbox == []
    db_session.expire_all()
    statuses = set((await db_session.execute(select(Schedule.status).where(Schedule.project_id == project_id))).scalars())
    assert statuses == {"cancelled"} and not statuses & {"Published", "published", "Completed", "completed"}
