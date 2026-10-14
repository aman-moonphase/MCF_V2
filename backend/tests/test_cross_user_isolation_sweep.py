"""Cross-user isolation sweep (Step 11 audit).

User A builds a complete journey (project, source, product, competitor with evidence, strategy, generated post,
evaluation, approval and a calendar plan). Then user B calls EVERY route that takes a resource ID — discovered from
the application's routes, so routes added later are covered automatically — using A's real IDs.

- No call may succeed (2xx) for B, and nothing about A may appear in B's responses.
- A's data must be exactly the same afterwards (B's writes are refused, not merely hidden).
- Routes that answer 422 before ownership could be checked are listed explicitly, so a gap cannot hide behind
  request validation without being reviewed.
Demo Mode; isolated test database; no external calls.
"""
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.routing import APIRoute
from sqlalchemy import select

from app.main import app
from app.models.competitor import Competitor, CompetitorEvidence
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.source import DocumentChunk, SourceDocument
from app.models.workflow_stage import WorkflowStage
from tests.test_promotion_strategy import other_client  # noqa: F401
from tests.test_scheduling_eligibility import approved_post

# Routes whose request validation (422) can run before the ownership check for the minimal body used here. Ownership on
# these is proven separately (see the per-route notes in the audit); the list must not grow unnoticed.
KNOWN_VALIDATED_FIRST: set = set()


async def snapshot(db):
    """Everything A owns, as comparable values (any write by B would change it)."""
    db.expire_all()
    out = {}
    for name, stmt in {
        "projects": select(Project.id, Project.title, Project.status, Project.current_stage, Project.product_id, Project.updated_at),
        "stages": select(WorkflowStage.id, WorkflowStage.status, WorkflowStage.data, WorkflowStage.updated_at),
        "products": select(Product.id, Product.profile_version, Product.understanding_status, Product.profile, Product.updated_at),
        "competitors": select(Competitor.id, Competitor.name, Competitor.analysis, Competitor.updated_at),
        "evidence": select(CompetitorEvidence.id),
        "sources": select(SourceDocument.id, SourceDocument.name, SourceDocument.status, SourceDocument.extracted_text),
        "chunks": select(DocumentChunk.id),
        "posts": select(GeneratedContent.id, GeneratedContent.content, GeneratedContent.status, GeneratedContent.version,
                        GeneratedContent.approved_version, GeneratedContent.updated_at),
        "evaluations": select(ContentEvaluation.id, ContentEvaluation.result),
        "schedules": select(Schedule.id, Schedule.status, Schedule.lock_version, Schedule.scheduled_at, Schedule.notes,
                            Schedule.cancelled_at, Schedule.updated_at),
    }.items():
        out[name] = sorted(json.dumps([str(v) for v in row], default=str) for row in (await db.execute(stmt)).all())
    return out


def body_for(path: str, method: str, ids: dict):
    """A minimal, valid-shaped body for each write route (so ownership — not validation — decides the response)."""
    p = path
    if method == "DELETE" or method == "GET":
        return None, None
    future = (datetime.now(timezone.utc) + timedelta(days=400)).replace(microsecond=0).isoformat()
    table = [
        ("/approve", {"project_id": ids["project"], "version": 1, "profile_version": 1, "limited_evidence": True}),
        ("/clarifications", {"project_id": ids["project"], "answers": [{"question_id": "q1", "answer": "Injected by user B"}]}),
        ("/competitor-analysis/approve", {"project_id": ids["project"], "version": 1, "limited_evidence": True}),
        ("/promotion-strategy/approve", {"project_id": ids["project"], "version": 1}),
        ("/competitors/discover", {"query": "x"}),
        ("/signals/ingest", {"title": "Injected signal", "source_url": "https://example.com/a"}),
        ("/ugc/ingest", {"title": "Injected thread", "source_url": "https://example.com/r"}),
        ("/competitors/{competitor_id}/evidence", None),
        ("/competitors", {"name": "Intruder Inc"}),
        ("/competitors/{competitor_id}", {"name": "Renamed by B"}),
        ("/profile", {"profile": {"name": "Changed by B"}}),
        ("/promotion-strategy", {"strategy": {}, "version": 1}),
        ("/generated-content/schedule", {"scheduled_at": future, "timezone": "UTC", "platform": "LinkedIn"}),
        ("/generated-content/approve", {"version": 1}),
        ("/generated-content", {"version": 1, "cta": "Changed by B"}),
        ("/evaluation", {"version": 1}),
        ("/product", {"product_id": ids["product"]}),
        ("/stages/{stage_type}", {"status": "Completed", "data": {"x": 1}}),
        ("/schedules/{schedule_id}/cancel", {"lock_version": 1}),
        ("/schedules/{schedule_id}", {"lock_version": 1, "notes": "Changed by B", "platform": "LinkedIn"}),
        ("/projects/{project_id}", {"title": "Renamed by B"}),
    ]
    for suffix, body in table:
        if p.endswith(suffix):
            return body, None
    return {}, None


async def build_journey(client, db):
    """User A's complete journey; returns (ids, markers)."""
    project_id, product_id = await approved_post(client)
    plan = await client.post(f"/api/projects/{project_id}/generated-content/schedule", json={
        "scheduled_at": "2047-03-02T09:00:00+05:30", "timezone": "Asia/Kolkata", "platform": "LinkedIn"})
    assert plan.status_code == 201, plan.text
    source = (await db.execute(select(SourceDocument).where(SourceDocument.project_id == project_id))).scalars().first()
    competitor = (await db.execute(select(Competitor).where(Competitor.product_id == product_id))).scalars().first()
    evidence = (await db.execute(select(CompetitorEvidence).where(CompetitorEvidence.competitor_id == competitor.id))).scalars().first()
    ids = {"project": str(project_id), "product": str(product_id), "source": str(source.id), "competitor": str(competitor.id),
           "evidence": str(evidence.id), "schedule": plan.json()["id"], "stage": "generate-content"}
    markers = {str(project_id), str(product_id), str(source.id), str(competitor.id), str(evidence.id), ids["schedule"],
               competitor.name}
    return ids, markers


def fill(url: str, ids: dict) -> str:
    mapping = {"project_id": ids["project"], "product_id": ids["product"], "source_id": ids["source"],
               "competitor_id": ids["competitor"], "evidence_id": ids["evidence"], "schedule_id": ids["schedule"],
               "stage_type": ids["stage"], "version": "1"}  # a strategy version number is not a secret id
    for key, value in mapping.items():
        url = url.replace("{" + key + "}", value)
    assert "{" not in url, f"unmapped path parameter in {url}"
    return url


@pytest.mark.asyncio
async def test_every_id_route_refuses_another_user(authenticated_client, other_client, db_session):
    ids, markers = await build_journey(authenticated_client, db_session)
    project_id, product_id = UUID(ids["project"]), UUID(ids["product"])
    before = await snapshot(db_session)

    swept, breaches, leaks, validated_first, other_status = 0, [], [], [], []
    for route in app.routes:
        if not isinstance(route, APIRoute) or "{" not in route.path:
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            url = fill(route.path, ids)
            kwargs = {}
            if route.path.endswith("/sources/ingest"):
                kwargs["data"] = {"source_type": "text", "content": "Injected by user B"}
            elif route.path.endswith("/evidence") and method == "POST":
                kwargs["data"] = {"evidence_type": "note", "content": "Injected by user B"}
            else:
                body, _ = body_for(route.path, method, ids)
                if body is not None:
                    kwargs["json"] = body
            res = await other_client.request(method, url, **kwargs)
            swept += 1
            label = f"{method} {route.path}"
            if res.status_code < 300:
                breaches.append((label, res.status_code))
            elif res.status_code == 422:
                validated_first.append(label)
            elif res.status_code not in (403, 404):
                other_status.append((label, res.status_code))  # e.g. a state conflict decided before ownership
            if any(m in res.text for m in markers):
                leaks.append(label)

    assert swept >= 44, f"expected the sweep to cover every ID-bearing route, got {swept}"
    assert not breaches, f"user B succeeded on: {breaches}"
    assert not other_status, f"refused with something other than 403/404 (ownership should decide first): {other_status}"
    assert not leaks, f"A's identifiers or names appeared in B's responses for: {leaks}"
    assert set(validated_first) <= KNOWN_VALIDATED_FIRST, f"answered 422 before ownership could be checked: {sorted(set(validated_first) - KNOWN_VALIDATED_FIRST)}"
    assert await snapshot(db_session) == before, "user B changed or removed user A's data"

    # List / overview endpoints (no path IDs): B's views never contain A's data.
    wide = {"start": "2047-01-01T00:00:00+00:00", "end": "2047-12-31T00:00:00+00:00", "include_cancelled": "true"}  # contains A's plan
    for url, params in (("/api/projects", None), ("/api/products", None), ("/api/schedules", {"include_cancelled": "true"}),
                        ("/api/schedules/calendar", wide), ("/api/diagnostics", None), ("/api/settings/me", None)):
        res = await other_client.get(url, params=params)
        assert res.status_code == 200, (url, res.text)
        assert not any(m in res.text for m in markers), f"A's data in B's {url}"
        assert "EvalCheck" not in res.text and "LedgerLeaf" not in res.text, f"A's product name in B's {url}"
    ingestion = (await other_client.get("/api/diagnostics")).json()["ingestion"]
    assert ingestion["sources_total"] == 0 and ingestion["chunks_total"] == 0  # A's sources are not B's

    # Control: the same views DO show the data to its owner (so B's empty views above are meaningful).
    mine = (await authenticated_client.get("/api/schedules/calendar", params=wide)).json()["entries"]
    assert ids["schedule"] in [e["id"] for e in mine]  # (the shared test user may own other plans from earlier tests)
    assert (await authenticated_client.get("/api/diagnostics")).json()["ingestion"]["sources_total"] >= 1

    # A still has full access to everything (the sweep did not lock or alter anything).
    assert (await authenticated_client.get(f"/api/schedules/{ids['schedule']}")).status_code == 200
    assert (await authenticated_client.get(f"/api/projects/{project_id}/generated-content")).json()["draft"]["status"] == "approved"


@pytest.mark.asyncio
async def test_get_routes_never_write_or_call_providers(authenticated_client, db_session, monkeypatch):
    """Reading is free: no GET route may create an AI/embedding provider, open a network connection, or write."""
    import socket

    from sqlalchemy import event

    from app.ai.providers import factory as ai_factory
    from app.ai.providers.embedding import factory as embedding_factory

    ids, _ = await build_journey(authenticated_client, db_session)
    from app.core.config import settings

    fake_keys = ("sk-ant-api03-SWEEP-NOT-A-REAL-KEY-111", "sk-proj-SWEEP-NOT-A-REAL-KEY-222")
    monkeypatch.setattr(settings, "ANTHROPIC_API_KEY", fake_keys[0])
    monkeypatch.setattr(settings, "OPENAI_API_KEY", fake_keys[1])
    secrets_to_find = [*fake_keys, settings.SECRET_KEY, "postgresql://", "postgresql+asyncpg://", "DATABASE_URL", "SECRET_KEY",
                       "ANTHROPIC_API_KEY=", "OPENAI_API_KEY="]
    if settings.POSTGRES_PASSWORD and len(settings.POSTGRES_PASSWORD) >= 12:
        secrets_to_find.append(settings.POSTGRES_PASSWORD)
    leaked: list = []

    def forbidden(*args, **kwargs):
        raise AssertionError("a GET route tried to create a provider or open a connection")

    monkeypatch.setattr(embedding_factory.EmbeddingProviderFactory, "get_provider", staticmethod(forbidden))
    for name in ("get_provider", "get_configured_provider"):
        if hasattr(ai_factory, name):
            monkeypatch.setattr(ai_factory, name, forbidden)
        if hasattr(ai_factory.AIProviderFactory, name):
            monkeypatch.setattr(ai_factory.AIProviderFactory, name, staticmethod(forbidden))
    monkeypatch.setattr(socket, "create_connection", forbidden)

    statements, swept, failures = [], 0, []
    connection = (await db_session.connection()).sync_connection
    record = lambda conn, cursor, statement, *a: statements.append(statement.lstrip().split(None, 1)[0].upper())  # noqa: E731
    event.listen(connection, "before_cursor_execute", record)
    try:
        for route in app.routes:
            if not isinstance(route, APIRoute) or "GET" not in route.methods or route.path.startswith(("/health", "/docs", "/openapi")):
                continue
            url = fill(route.path, ids)
            params = None
            if url.endswith("/schedules/calendar"):
                params = {"start": "2047-01-01T00:00:00+00:00", "end": "2047-12-31T00:00:00+00:00"}
            res = await authenticated_client.get(url, params=params)
            swept += 1
            if res.status_code >= 500:
                failures.append((route.path, res.status_code))
            leaked += [(route.path, secret[:6] + "…") for secret in secrets_to_find if secret and secret in res.text]
    finally:
        event.remove(connection, "before_cursor_execute", record)
    assert swept >= 15, swept
    assert not failures, f"GET routes answered with a server error: {failures}"
    assert not leaked, f"secret-shaped values appeared in GET responses: {leaked}"
    writes = {s_ for s_ in statements if s_ not in ("SELECT", "SHOW", "SET", "BEGIN", "ROLLBACK", "COMMIT")}
    assert not writes, f"GET routes issued write statements: {writes}"
