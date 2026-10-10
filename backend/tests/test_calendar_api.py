"""Calendar & content planning, step 4: GET /api/schedules/calendar (read-only range listing).

Each test uses its own time window, so rows written by other tests for the shared test user never interfere.
Entries are created through the planning API (Demo Mode) or written directly to the isolated test database.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import event, func, select

from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.user import User
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_scheduling_eligibility import approved_post

UTC = timezone.utc
IST = ZoneInfo("Asia/Kolkata")
URL = "/api/schedules/calendar"


def rng(start: datetime, end: datetime, **extra):
    return {"start": start.isoformat(), "end": end.isoformat(), **extra}


async def calendar(client, start, end, expected=200, **extra):
    res = await client.get(URL, params=rng(start, end, **extra))
    assert res.status_code == expected, res.text
    return res.json()


def ids(payload):
    return [e["id"] for e in payload["entries"]]


async def owned_project(db, user_id, product=True, title="Calendar campaign"):
    product_row = None
    if product:
        product_row = Product(user_id=user_id, name=f"Calendar product {uuid.uuid4().hex[:6]}")
        db.add(product_row)
        await db.flush()
    project = Project(title=title, source_type="Text Idea", source_reference="x", user_id=user_id,
                      product_id=product_row.id if product_row else None)
    db.add(project)
    await db.flush()
    return project, product_row


def legacy(project, when, status_="Scheduled", **extra):
    return Schedule(project_id=project.id, platform="LinkedIn", scheduled_at=when, status=status_, **extra)


def planned(project, post, when, **extra):
    fields = dict(project_id=project.id, product_id=post.product_id, generated_content_id=post.id,
                  content_version=post.version, content_digest=extra.pop("digest", None), content_type=post.content_type,
                  platform="LinkedIn", scheduled_at=when, status="planned", timezone="Asia/Kolkata")
    fields.update(extra)
    return Schedule(**fields)


async def a_post(db, project, product, version=1, content=None):
    from app.services.scheduling_eligibility import content_digest
    post = GeneratedContent(project_id=project.id, product_id=product.id, content_type="Social Post", platform="linkedin",
                            content=content or {"hook": "Plan me", "body": "Body"}, status="approved", version=version,
                            approved_version=version)
    db.add(post)
    await db.flush()
    return post, content_digest(post.content)


# ─── Range, order and validation ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_half_open_range_and_stable_order(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project, _ = await owned_project(db_session, user_id, product=False, title="Order test")
    t0 = datetime(2031, 5, 1, tzinfo=UTC)
    rows = [legacy(project, t0 - timedelta(microseconds=1)),            # just before start: excluded
            legacy(project, t0 + timedelta(hours=5)),
            legacy(project, t0),                                         # exactly start: included
            legacy(project, t0 + timedelta(hours=5)),                    # same instant: tie broken by created_at, id
            legacy(project, t0 + timedelta(days=1))]                     # exactly end: excluded
    created = datetime(2026, 1, 1, tzinfo=UTC)
    for i, row in enumerate(rows):
        row.created_at = created + timedelta(minutes=i)
    db_session.add_all(rows)
    await db_session.commit()
    payload = await calendar(authenticated_client, t0, t0 + timedelta(days=1))
    assert ids(payload) == [str(rows[2].id), str(rows[1].id), str(rows[3].id)]
    times = [e["scheduled_at"] for e in payload["entries"]]
    assert times == sorted(times)
    again = await calendar(authenticated_client, t0, t0 + timedelta(days=1))
    assert ids(again) == ids(payload)  # deterministic


@pytest.mark.asyncio
async def test_offsets_are_instants(authenticated_client, db_session, test_user):
    user_id = test_user.id
    project, _ = await owned_project(db_session, user_id, product=False)
    morning_ist = datetime(2032, 3, 2, 9, 0, tzinfo=IST)  # 03:30 UTC
    row = legacy(project, morning_ist)
    db_session.add(row)
    await db_session.commit()
    # The same range expressed in IST or in UTC returns the same entry.
    ist_day = await calendar(authenticated_client, datetime(2032, 3, 2, tzinfo=IST), datetime(2032, 3, 3, tzinfo=IST))
    utc_window = await calendar(authenticated_client, datetime(2032, 3, 2, 3, 30, tzinfo=UTC), datetime(2032, 3, 2, 3, 31, tzinfo=UTC))
    assert ids(ist_day) == ids(utc_window) == [str(row.id)]
    # A UTC day that ends before 03:30 UTC does not include it; local display uses the requested zone.
    assert ids(await calendar(authenticated_client, datetime(2032, 3, 1, 3, 31, tzinfo=UTC), datetime(2032, 3, 2, 3, 30, tzinfo=UTC))) == []
    local = await calendar(authenticated_client, datetime(2032, 3, 2, tzinfo=UTC), datetime(2032, 3, 3, tzinfo=UTC), timezone="Asia/Kolkata")
    entry = local["entries"][0]
    assert entry["scheduled_at_local"].startswith("2032-03-02T09:00:00+05:30") and local["timezone"] == "Asia/Kolkata"


@pytest.mark.asyncio
async def test_invalid_ranges_are_rejected(authenticated_client):
    start = datetime(2033, 1, 1, tzinfo=UTC)
    for params in (
        {"start": "2033-01-01T00:00:00", "end": "2033-01-02T00:00:00+00:00"},       # no offset
        {"start": "2033-01-01T00:00:00+00:00", "end": "2033-01-02T00:00:00"},
        rng(start, start),                                                         # empty
        rng(start, start - timedelta(days=1)),                                     # reversed
        rng(start, start + timedelta(days=367)),                                   # too long
        rng(start, start + timedelta(days=1), timezone="Mars/Base"),
        rng(start, start + timedelta(days=1), timezone="IST"),
        {"start": "not-a-date", "end": "2033-01-02T00:00:00+00:00"},
        {"end": "2033-01-02T00:00:00+00:00"},
    ):
        res = await authenticated_client.get(URL, params=params)
        assert res.status_code == 422, (params, res.text)
    assert (await authenticated_client.get(URL, params=rng(start, start + timedelta(days=366)))).status_code == 200


# ─── Ownership, products and cancelled entries ──────────────────────────────

@pytest.mark.asyncio
async def test_product_filter_and_ownership(authenticated_client, other_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2034, 6, 1, tzinfo=UTC)
    mine_a, product_a = await owned_project(db_session, user_id, title="A campaign")
    mine_b, product_b = await owned_project(db_session, user_id, title="B campaign")
    other_user = User(email=f"cal-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", is_active=True)
    db_session.add(other_user)
    await db_session.flush()
    theirs, their_product = await owned_project(db_session, other_user.id, title="Their campaign")
    a, b, t = legacy(mine_a, t0 + timedelta(hours=1)), legacy(mine_b, t0 + timedelta(hours=2)), legacy(theirs, t0 + timedelta(hours=3))
    db_session.add_all([a, b, t])
    await db_session.commit()

    everything = await calendar(authenticated_client, t0, t0 + timedelta(days=1))
    assert ids(everything) == [str(a.id), str(b.id)] and "Their campaign" not in str(everything)
    assert everything["entries"][0]["product_id"] == str(product_a.id) and everything["entries"][0]["product_name"] == product_a.name
    only_a = await calendar(authenticated_client, t0, t0 + timedelta(days=1), product_id=str(product_a.id))
    assert ids(only_a) == [str(a.id)]
    # Another user's product is indistinguishable from a missing one.
    hidden = await authenticated_client.get(URL, params=rng(t0, t0 + timedelta(days=1), product_id=str(their_product.id)))
    missing = await authenticated_client.get(URL, params=rng(t0, t0 + timedelta(days=1), product_id=str(uuid.uuid4())))
    assert hidden.status_code == missing.status_code == 404 and hidden.json() == missing.json()


@pytest.mark.asyncio
async def test_cancelled_entries_only_on_request(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2035, 2, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id)
    post, digest = await a_post(db_session, project, product)
    active = planned(project, post, t0 + timedelta(hours=1), digest=digest)
    gone = planned(project, post, t0 + timedelta(hours=2), digest=digest, status="cancelled", cancelled_at=datetime.now(UTC))
    db_session.add_all([active, gone])
    await db_session.commit()
    assert ids(await calendar(authenticated_client, t0, t0 + timedelta(days=1))) == [str(active.id)]
    both = await calendar(authenticated_client, t0, t0 + timedelta(days=1), include_cancelled="true")
    assert ids(both) == [str(active.id), str(gone.id)] and both["include_cancelled"] is True
    cancelled = both["entries"][1]
    assert cancelled["status"] == "cancelled" and cancelled["cancelled_at"] and cancelled["conditions"] == []


# ─── Legacy and planned entries, derived conditions ─────────────────────────

@pytest.mark.asyncio
async def test_legacy_entries_have_no_invented_links(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2036, 4, 1, tzinfo=UTC)
    project, _ = await owned_project(db_session, user_id, product=False, title="Legacy project")
    row = legacy(project, t0 + timedelta(hours=1))
    db_session.add(row)
    await db_session.commit()
    (entry,) = (await calendar(authenticated_client, t0, t0 + timedelta(days=1)))["entries"]
    assert entry["is_legacy"] is True and entry["status"] == "Scheduled" and entry["project_title"] == "Legacy project"
    for key in ("product_id", "product_name", "generated_content_id", "content_version", "content_digest",
                "current_content_status", "current_content_version", "timezone", "content_type"):
        assert entry[key] is None, key
    assert entry["conditions"] == []  # in the future, nothing to flag


@pytest.mark.asyncio
async def test_planned_entry_conditions(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2037, 7, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id)
    post, digest = await a_post(db_session, project, product, version=3)
    unchanged = planned(project, post, t0 + timedelta(hours=1), digest=digest)
    other_version = planned(project, post, t0 + timedelta(hours=2), digest=digest, content_version=2)
    other_digest = planned(project, post, t0 + timedelta(hours=3), digest="0" * 64)
    lost_post = planned(project, post, t0 + timedelta(hours=4), digest=digest, generated_content_id=None)
    db_session.add_all([unchanged, other_version, other_digest, lost_post])
    await db_session.commit()
    entries = {e["id"]: e for e in (await calendar(authenticated_client, t0, t0 + timedelta(days=1)))["entries"]}

    ok = entries[str(unchanged.id)]
    assert ok["conditions"] == [] and ok["status"] == "planned" and ok["is_legacy"] is False
    assert (ok["generated_content_id"], ok["content_version"], ok["content_digest"]) == (str(post.id), 3, digest)
    assert (ok["current_content_status"], ok["current_content_version"]) == ("approved", 3)
    assert (ok["product_id"], ok["product_name"], ok["timezone"], ok["content_type"]) == (str(product.id), product.name, "Asia/Kolkata", "Social Post")
    assert entries[str(other_version.id)]["conditions"] == ["post_changed"]
    assert entries[str(other_digest.id)]["conditions"] == ["post_changed"]
    lost = entries[str(lost_post.id)]
    assert lost["conditions"] == ["post_missing"] and lost["current_content_status"] is None
    assert lost["content_version"] == 3 and lost["is_legacy"] is False  # what was planned is still shown
    # No post text, claims or evidence in the listing.
    assert "Plan me" not in str(entries) and "claims" not in str(entries) and "evidence" not in str(entries)


@pytest.mark.asyncio
async def test_post_deleted_after_planning_is_missing(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2038, 1, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id)
    post, digest = await a_post(db_session, project, product)
    row = planned(project, post, t0 + timedelta(hours=1), digest=digest)
    db_session.add(row)
    await db_session.commit()
    await db_session.delete(post)  # the FK sets generated_content_id to NULL; version and digest are kept
    await db_session.commit()
    (entry,) = (await calendar(authenticated_client, t0, t0 + timedelta(days=1)))["entries"]
    assert entry["conditions"] == ["post_missing"] and entry["generated_content_id"] is None and entry["content_version"] == 1


@pytest.mark.asyncio
async def test_passed_dates_are_not_published(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2001, 3, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id)
    post, digest = await a_post(db_session, project, product)
    plan = planned(project, post, t0 + timedelta(hours=1), digest=digest)
    old = legacy(project, t0 + timedelta(hours=2))
    gone = planned(project, post, t0 + timedelta(hours=3), digest=digest, status="cancelled", cancelled_at=t0)
    db_session.add_all([plan, old, gone])
    await db_session.commit()
    entries = (await calendar(authenticated_client, t0, t0 + timedelta(days=1), include_cancelled="true"))["entries"]
    assert [(e["status"], e["conditions"]) for e in entries] == [
        ("planned", ["date_passed"]), ("Scheduled", ["date_passed"]), ("cancelled", [])]
    assert "publish" not in str(entries).lower()


# ─── Mismatched / foreign references fail safely ────────────────────────────

@pytest.mark.asyncio
async def test_cross_product_and_cross_project_references(authenticated_client, db_session, test_user):
    user_id = test_user.id
    t0 = datetime(2039, 9, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id, title="Mine")
    _, my_other_product = await owned_project(db_session, user_id, title="Mine too")
    stranger = User(email=f"cal-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", is_active=True)
    db_session.add(stranger)
    await db_session.flush()
    their_project, their_product = await owned_project(db_session, stranger.id, title="Secret campaign")
    their_post, their_digest = await a_post(db_session, their_project, their_product, content={"hook": "Secret hook"})
    my_post, digest = await a_post(db_session, project, product)

    moved = planned(project, my_post, t0 + timedelta(hours=1), digest=digest, product_id=my_other_product.id)
    foreign_product = planned(project, my_post, t0 + timedelta(hours=2), digest=digest, product_id=their_product.id)
    foreign_post = planned(project, my_post, t0 + timedelta(hours=3), digest=their_digest, generated_content_id=their_post.id)
    db_session.add_all([moved, foreign_product, foreign_post])
    await db_session.commit()
    payload = await calendar(authenticated_client, t0, t0 + timedelta(days=1))
    entries = {e["id"]: e for e in payload["entries"]}

    # Another of my products: shown (it is mine) but flagged as not matching the project's product.
    assert entries[str(moved.id)]["conditions"] == ["product_mismatch"]
    assert entries[str(moved.id)]["product_name"] == my_other_product.name
    # Another user's product: nothing about it is returned.
    leaked = entries[str(foreign_product.id)]
    assert leaked["conditions"] == ["product_mismatch"] and leaked["product_id"] is None and leaked["product_name"] is None
    # A post from another user's project is never resolved: treated as missing, its status/version not shown.
    alien = entries[str(foreign_post.id)]
    assert alien["conditions"] == ["post_missing"] and alien["current_content_status"] is None
    assert alien["current_content_version"] is None
    for secret in (their_product.name, "Secret campaign", "Secret hook"):
        assert secret not in str(payload)
    # Filtering by the project's own product finds the entries planned for that product only.
    assert ids(await calendar(authenticated_client, t0, t0 + timedelta(days=1), product_id=str(my_other_product.id))) == [str(moved.id)]


# ─── Real planning flow, compatibility, read-only ───────────────────────────

@pytest.mark.asyncio
async def test_planned_through_the_api_and_legacy_listing_unchanged(authenticated_client, db_session):
    project_id, product_id = await approved_post(authenticated_client)
    when = datetime(2040, 2, 3, 9, 0, tzinfo=IST)
    res = await authenticated_client.post(f"/api/projects/{project_id}/generated-content/schedule",
                                          json={"scheduled_at": when.isoformat(), "timezone": "Asia/Kolkata", "platform": "LinkedIn"})
    assert res.status_code == 201, res.text
    planned_id = res.json()["id"]
    (entry,) = (await calendar(authenticated_client, datetime(2040, 2, 3, tzinfo=IST), datetime(2040, 2, 4, tzinfo=IST),
                               product_id=str(product_id)))["entries"]
    assert entry["id"] == planned_id and entry["conditions"] == [] and entry["product_id"] == str(product_id)
    assert entry["current_content_status"] == "approved" and entry["current_content_version"] == entry["content_version"] == 1

    # The existing listing keeps its shape (the current calendar UI reads it).
    listed = (await authenticated_client.get("/api/schedules")).json()
    row = next(e for e in listed if e["id"] == planned_id)
    for key in ("id", "project_id", "project_title", "platform", "scheduled_at", "status", "created_at", "updated_at"):
        assert key in row
    assert "conditions" not in row and "is_legacy" not in row


@pytest.mark.asyncio
async def test_listing_is_read_only(authenticated_client, db_session, test_user, smtp_outbox, monkeypatch):
    import requests
    import socket

    def no_network(*args, **kwargs):
        raise AssertionError("listing must not make network calls")

    monkeypatch.setattr(requests.Session, "request", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    user_id = test_user.id
    t0 = datetime(2041, 1, 1, tzinfo=UTC)
    project, product = await owned_project(db_session, user_id)
    post, digest = await a_post(db_session, project, product)
    db_session.add_all([planned(project, post, t0 + timedelta(hours=1), digest=digest), legacy(project, t0 + timedelta(hours=2))])
    await db_session.commit()
    product_id = product.id

    async def snapshot():
        db_session.expire_all()
        rows = (await db_session.execute(select(Schedule.id, Schedule.status, Schedule.lock_version, Schedule.updated_at,
                                                Schedule.cancelled_at).order_by(Schedule.id))).all()
        posts = (await db_session.execute(select(GeneratedContent.id, GeneratedContent.status, GeneratedContent.version,
                                                 GeneratedContent.updated_at).order_by(GeneratedContent.id))).all()
        evaluations = (await db_session.execute(select(func.count(ContentEvaluation.id)))).scalar()
        return rows, posts, evaluations

    before = await snapshot()
    statements = []
    connection = (await db_session.connection()).sync_connection
    record = lambda conn, cursor, statement, *a: statements.append(statement.lstrip().split(None, 1)[0].upper())  # noqa: E731
    event.listen(connection, "before_cursor_execute", record)
    try:
        for extra in ({}, {"include_cancelled": "true"}, {"product_id": str(product_id), "timezone": "Asia/Kolkata"}):
            await calendar(authenticated_client, t0, t0 + timedelta(days=1), **extra)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert statements and set(statements) <= {"SELECT"}, set(statements)
    assert await snapshot() == before and smtp_outbox == []


@pytest.mark.asyncio
async def test_requires_authentication(client):
    start = datetime(2042, 1, 1, tzinfo=UTC)
    assert (await client.get(URL, params=rng(start, start + timedelta(days=1)))).status_code == 401
