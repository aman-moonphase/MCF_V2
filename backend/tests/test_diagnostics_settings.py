"""Step 10: Diagnostics (read-only health overview) and per-user Settings.

Diagnostics: healthy / unavailable dependencies ("Not checked" for checks that could not run), credentials reported
as booleans only, migration revision vs the code's head, ingestion health for the caller's own sources (stale and
failed), no writes and no external calls. Settings: defaults, validation, persistence, isolation.
Isolated test database; Demo Mode; nothing is sent anywhere.
"""
import socket
from uuid import UUID

import pytest
from sqlalchemy import event, text, update

from app.api.deps import get_current_user
from app.core.config import settings
from app.db.session import get_db
from app.main import app
from app.models.source import SourceDocument
from app.services import diagnostics_service
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_rag_research_grounding import ingest, make_project

FAKE_SECRET = "sk-ant-api03-TEST-ONLY-NOT-A-REAL-KEY-zzz123"
URL = "/api/diagnostics"


async def diagnostics(client):
    res = await client.get(URL)
    assert res.status_code == 200, res.text
    return res.json()


# ─── Diagnostics: healthy state, shape and compatibility ────────────────────

@pytest.mark.asyncio
async def test_healthy_overview_in_demo_mode(authenticated_client):
    data = await diagnostics(authenticated_client)
    # The original sections are all still there (existing page and test keep working).
    for key in ("backend", "database", "vector_store", "ai", "embeddings", "rag", "environment"):
        assert key in data
    assert data["checked_at"] and data["overall"]["status"] in ("Healthy", "Warning", "Unknown")
    assert data["database"]["status"] == "Healthy" and data["vector_store"]["status"] == "Enabled"
    ai = data["ai"]
    assert (ai["mode"], ai["provider"], ai["status"]) == ("demo", "demo", "Ready")  # same status as before
    assert ai["credentials_configured"] is False and ai["connection_verified"] is False and ai["may_incur_charges"] is False
    emb = data["embeddings"]
    assert (emb["provider"], emb["model"], emb["semantic"], emb["status"]) == ("demo", "demo-hash-1536", False, "Ready")
    assert "keyword" in emb["message"]
    assert data["rag"]["status"] == "Ready" and data["environment"]["mode"] == "Demo"


@pytest.mark.asyncio
async def test_requires_authentication(client):
    assert (await client.get(URL)).status_code in (401, 403)
    assert (await client.get("/api/settings/me")).status_code in (401, 403)
    assert (await client.put("/api/settings/me", json={"calendar_default_view": "week", "default_plan_time": "10:00"})).status_code in (401, 403)


# ─── Credentials: booleans only, never verified ─────────────────────────────

@pytest.mark.asyncio
async def test_configured_real_provider_is_not_claimed_verified(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", FAKE_SECRET)
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", FAKE_SECRET + "-openai")
    res = await authenticated_client.get(URL)
    data = res.json()
    ai, emb = data["ai"], data["embeddings"]
    assert ai["mode"] == "real" and ai["credentials_configured"] is True and ai["connection_verified"] is False
    # "Ready" = configured (its existing meaning); the connection is explicitly not verified.
    assert ai["status"] == "Ready" and "not verified" in ai["message"] and ai["may_incur_charges"] is True
    assert emb["semantic"] is True and emb["credentials_configured"] is True and emb["status"] == "Ready"
    assert "not verified" in emb["message"]
    for fragment in (FAKE_SECRET, "TEST-ONLY", "zzz123", "sk-ant"):
        assert fragment not in res.text


@pytest.mark.asyncio
async def test_missing_credentials_are_reported_without_values(authenticated_client, monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", "")
    monkeypatch.setattr(settings, "EMBEDDING_PROVIDER", "openai")
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "")
    data = await diagnostics(authenticated_client)
    assert data["ai"]["status"] == "Not configured" and data["ai"]["credentials_configured"] is False
    assert "ANTHROPIC_API_KEY is not set" in data["ai"]["message"]
    assert data["embeddings"]["status"] == "Not configured" and data["embeddings"]["credentials_configured"] is False
    assert data["rag"]["status"] == "Degraded" and data["overall"]["status"] == "Warning"


# ─── Migration revision ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_revision_states(authenticated_client, db_session):
    head = diagnostics_service.migration_heads()
    assert len(head) == 1
    # The test database is built from the models (no migration record): reported as Unknown, not as healthy.
    assert (await diagnostics(authenticated_client))["migration"]["status"] == "Unknown"

    # A temporary alembic_version on this test connection (the request uses the same session).
    await db_session.execute(text("CREATE TEMP TABLE alembic_version (version_num varchar(32) NOT NULL)"))
    await db_session.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": head[0]})
    up_to_date = (await diagnostics(authenticated_client))["migration"]
    assert (up_to_date["status"], up_to_date["current_revision"], up_to_date["head_revision"]) == ("Healthy", head[0], head[0])

    await db_session.execute(text("UPDATE alembic_version SET version_num = 'f6a7b8c9d0e1'"))  # an older, known revision
    behind = (await diagnostics(authenticated_client))["migration"]
    assert behind["status"] == "Warning" and "behind" in behind["message"] and behind["current_revision"] == "f6a7b8c9d0e1"

    await db_session.execute(text("UPDATE alembic_version SET version_num = 'ffffffffffff'"))  # unknown to this code
    unknown = (await diagnostics(authenticated_client))["migration"]
    assert unknown["status"] == "Warning" and "does not know" in unknown["message"]
    await db_session.rollback()


# ─── Unavailable dependencies ───────────────────────────────────────────────

class _BrokenSession:
    """A session whose every query fails with a driver error that contains connection details."""

    async def execute(self, *args, **kwargs):
        from sqlalchemy.exc import OperationalError
        raise OperationalError("SELECT 1", {}, Exception(f"could not connect to postgresql://mcf:{FAKE_SECRET}@db.internal:5444/mcf_db"))


@pytest.mark.asyncio
async def test_database_unavailable_is_reported_safely(client, test_user):
    user_id = test_user.id

    async def broken_db():
        yield _BrokenSession()

    class _User:
        id = user_id

    previous_db = app.dependency_overrides.get(get_db)
    app.dependency_overrides[get_db] = broken_db
    app.dependency_overrides[get_current_user] = lambda: _User()
    try:
        res = await client.get(URL)
        health = await client.get("/health/db")
    finally:
        app.dependency_overrides.pop(get_current_user, None)
        if previous_db is not None:
            app.dependency_overrides[get_db] = previous_db
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["database"]["status"] == "Unavailable" and "OperationalError" in data["database"]["message"]
    for key in ("vector_store", "migration", "rag", "ingestion"):
        assert data[key]["status"] == "Not checked", key  # did not run — not "failed"
    assert data["overall"]["status"] == "Unavailable"
    assert health.status_code == 503 and health.json()["detail"] == "Database unreachable (OperationalError)"
    for fragment in (FAKE_SECRET, "db.internal", "postgresql://", "mcf:"):
        assert fragment not in res.text and fragment not in health.text


# ─── Ingestion health: own sources only, stale and failed ───────────────────

@pytest.mark.asyncio
async def test_ingestion_health_is_scoped_and_detects_stale_and_failed(authenticated_client, other_client, db_session, monkeypatch):
    before = (await diagnostics(authenticated_client))["ingestion"]

    # Someone else's sources never show up in my figures or names.
    theirs = await make_project(other_client, "Their project")
    await ingest(other_client, theirs, "ZebraFrost private launch notes for a secret product.")
    assert (await diagnostics(authenticated_client))["ingestion"]["sources_total"] == before["sources_total"]

    mine = await make_project(authenticated_client, "Diagnostics project")
    res = await ingest(authenticated_client, mine, "LedgerLeaf sends GST invoices and payment reminders to freelance clients.")
    source_id = res.json()["id"]
    after = (await diagnostics(authenticated_client))["ingestion"]
    assert after["sources_total"] == before["sources_total"] + 1 and after["chunks_total"] > before["chunks_total"]

    # The source text changes without re-indexing: its chunks are stale (the same rule retrieval uses).
    await db_session.execute(update(SourceDocument).where(SourceDocument.id == UUID(source_id))
                             .values(extracted_text="Completely different text now."))
    await db_session.commit()
    stale = (await diagnostics(authenticated_client))["ingestion"]
    assert stale["stale_chunks"] > before["stale_chunks"] and stale["status"] == "Warning" and "re-index" in stale["message"]

    # A failed ingestion is listed by name for its owner only.
    from app.ai.providers.embedding.demo import DemoEmbeddingProvider

    async def broken(self, texts):
        raise RuntimeError("embedding failed")

    monkeypatch.setattr(DemoEmbeddingProvider, "embed_documents", broken)
    failing_project = await make_project(authenticated_client, "Failing project")
    await ingest(authenticated_client, failing_project, "QuokkaMint text that fails to index.")
    monkeypatch.undo()
    failed = (await diagnostics(authenticated_client))["ingestion"]
    assert failed["sources_by_status"].get("failed", 0) == before["sources_by_status"].get("failed", 0) + 1
    assert failed["status"] == "Warning" and "failed to ingest" in failed["message"]
    assert len(failed["failed_sources"]) >= 1
    text_dump = str(await diagnostics(authenticated_client))
    assert "ZebraFrost" not in text_dump and "Their project" not in text_dump
    their_view = str(await diagnostics(other_client))
    assert "QuokkaMint" not in their_view and "Diagnostics project" not in their_view


# ─── Read-only and no external calls ────────────────────────────────────────

@pytest.mark.asyncio
async def test_diagnostics_never_write_or_call_out(authenticated_client, db_session, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("diagnostics must not create providers or open network connections")

    from app.ai.providers.embedding import factory as embedding_factory
    from app.ai.providers import factory as ai_factory

    monkeypatch.setattr(embedding_factory.EmbeddingProviderFactory, "get_provider", staticmethod(forbidden))
    for name in ("get_provider", "get_configured_provider"):
        if hasattr(ai_factory, name):
            monkeypatch.setattr(ai_factory, name, forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)

    statements = []
    connection = (await db_session.connection()).sync_connection
    record = lambda conn, cursor, statement, *a: statements.append(statement.lstrip().split(None, 1)[0].upper())  # noqa: E731
    event.listen(connection, "before_cursor_execute", record)
    try:
        for _ in range(2):
            await diagnostics(authenticated_client)
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert statements and set(statements) <= {"SELECT"}, set(statements)


# ─── Settings ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_settings_defaults_save_and_persist(authenticated_client, other_client):
    res = await authenticated_client.get("/api/settings/me")
    assert res.status_code == 200
    initial = res.json()
    assert set(initial) == {"timezone", "calendar_default_view", "default_plan_time", "saved", "updated_at"}
    if not initial["saved"]:
        assert (initial["timezone"], initial["calendar_default_view"], initial["default_plan_time"]) == (None, "month", "09:00")

    saved = await authenticated_client.put("/api/settings/me", json={
        "timezone": "Asia/Kolkata", "calendar_default_view": "week", "default_plan_time": "10:30"})
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["timezone"], body["calendar_default_view"], body["default_plan_time"], body["saved"]) == ("Asia/Kolkata", "week", "10:30", True)
    assert body["updated_at"]

    # Persisted: read back from a fresh session.
    from tests.conftest import TestingSessionLocal
    from app.models.user_settings import UserSettings
    from sqlalchemy import select
    async with TestingSessionLocal() as fresh:
        rows = (await fresh.execute(select(UserSettings))).scalars().all()
        mine = [r for r in rows if r.timezone == "Asia/Kolkata" and r.default_plan_time == "10:30" and r.calendar_default_view == "week"]
        assert mine
    again = (await authenticated_client.get("/api/settings/me")).json()
    assert (again["timezone"], again["calendar_default_view"], again["default_plan_time"], again["saved"]) == ("Asia/Kolkata", "week", "10:30", True)

    # Clearing the zone (= use the browser's) is allowed.
    cleared = await authenticated_client.put("/api/settings/me", json={"timezone": None, "calendar_default_view": "day", "default_plan_time": "08:05"})
    assert cleared.status_code == 200 and cleared.json()["timezone"] is None and cleared.json()["calendar_default_view"] == "day"

    # Another user's settings are separate.
    theirs = (await other_client.get("/api/settings/me")).json()
    assert theirs["saved"] is False and theirs["calendar_default_view"] == "month"
    await other_client.put("/api/settings/me", json={"timezone": "Europe/London", "calendar_default_view": "month", "default_plan_time": "07:00"})
    mine_after = (await authenticated_client.get("/api/settings/me")).json()
    assert (mine_after["timezone"], mine_after["calendar_default_view"], mine_after["default_plan_time"]) == (None, "day", "08:05")


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"timezone": "Mars/Base", "calendar_default_view": "month", "default_plan_time": "09:00"},
    {"timezone": "IST", "calendar_default_view": "month", "default_plan_time": "09:00"},
    {"timezone": None, "calendar_default_view": "year", "default_plan_time": "09:00"},
    {"timezone": None, "calendar_default_view": "month", "default_plan_time": "24:00"},
    {"timezone": None, "calendar_default_view": "month", "default_plan_time": "9:00"},
    {"timezone": None, "calendar_default_view": "month"},
    {"timezone": None, "calendar_default_view": "month", "default_plan_time": "09:00", "anthropic_api_key": "x"},
    {"timezone": None, "calendar_default_view": "month", "default_plan_time": "09:00", "ai_provider": "claude"},
])
async def test_settings_validation(authenticated_client, payload):
    before = (await authenticated_client.get("/api/settings/me")).json()
    res = await authenticated_client.put("/api/settings/me", json=payload)
    assert res.status_code == 422, res.text
    assert (await authenticated_client.get("/api/settings/me")).json() == before  # nothing saved
