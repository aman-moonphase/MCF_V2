"""Competitor Analysis API: CRUD, evidence, prerequisites, isolation, discovery, analysis, comparison, approval."""
import uuid
from datetime import timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.competitor import Competitor, CompetitorEvidence
from app.models.source import SourceDocument
from app.models.user import User
from app.services.extraction_service import ExtractionResult, ExtractionService

SOURCE = (
    "Product: LedgerLeaf - a bookkeeping app for freelance designers in India. "
    "Features: GST invoice generation, expense categorisation, and a client payment tracker. "
    "Target users: solo designers and small studios. "
    "Main alternatives people use today: Zoho Books, Vyapar. "
    "Differentiator: WhatsApp invoice sharing, setup in five minutes."
)
ZOHO_PAGE = (
    "Zoho Books is online accounting software for small businesses. "
    "Create GST invoices and track payments in one place. "
    "Read our blog for accounting tips. Follow us on LinkedIn."
)


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def make_product(client, approve=True):
    res = await client.post("/api/projects", json={"title": "LedgerLeaf launch", "source_type": "Text Idea", "source_reference": "LedgerLeaf"})
    project_id = res.json()["id"]
    await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": SOURCE})
    product = (await client.post(f"/api/projects/{project_id}/product-understanding")).json()
    if approve:
        res = await client.post(f"/api/products/{product['id']}/approve", json={"project_id": project_id, "profile_version": product["profile_version"]})
        assert res.status_code == 200
    return project_id, product["id"]


async def add_competitor(client, product_id, **fields):
    res = await client.post(f"/api/products/{product_id}/competitors", json={"name": "Zoho Books", **fields})
    assert res.status_code == 201, res.text
    return res.json()


async def add_note(client, product_id, competitor_id, text=ZOHO_PAGE):
    res = await client.post(f"/api/products/{product_id}/competitors/{competitor_id}/evidence", data={"evidence_type": "note", "content": text})
    assert res.status_code == 201, res.text
    return res.json()


def state_url(product_id):
    return f"/api/products/{product_id}/competitor-analysis"


@pytest.fixture
async def other_client(db_session):
    user = User(email=f"rival-{uuid.uuid4().hex[:8]}@example.com", hashed_password=get_password_hash("x" * 12), is_active=True)
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(subject=str(user.id), expires_delta=timedelta(minutes=30))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac


# ─── Workflow + prerequisite ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_sits_between_product_understanding_and_content_type(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    stages = [s["stage_type"] for s in res.json()["stages"]]
    i = stages.index("competitor-analysis")
    assert stages[i - 1] == "product-understanding" and stages[i + 1] == "promotion-strategy"


@pytest.mark.asyncio
async def test_requires_an_approved_product_profile(authenticated_client):
    _, product_id = await make_product(authenticated_client, approve=False)
    assert (await authenticated_client.get(state_url(product_id))).json()["status"] == "locked"
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors", json={"name": "Zoho Books"})
    assert res.status_code == 409
    assert (await authenticated_client.post(f"/api/products/{product_id}/competitors/discover")).status_code == 409


# ─── CRUD ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_competitor_crud(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id, website_url="zoho.com/books")
    assert c["website_url"] == "https://zoho.com/books"
    assert c["origin"] == "user" and c["verification"] == "user_added" and c["analysis_status"] == "not_analyzed"

    dup = await authenticated_client.post(f"/api/products/{product_id}/competitors", json={"name": "zoho books"})
    assert dup.status_code == 409
    bad = await authenticated_client.post(f"/api/products/{product_id}/competitors", json={"name": "X", "website_url": "ftp://x"})
    assert bad.status_code == 422

    url = f"/api/products/{product_id}/competitors/{c['id']}"
    res = await authenticated_client.patch(url, json={"notes": "Their homepage pushes GST compliance.", "description": "Accounting suite"})
    assert res.status_code == 200 and res.json()["notes"].startswith("Their homepage")
    assert (await authenticated_client.patch(url, json={"name": "  "})).status_code == 422

    assert (await authenticated_client.delete(url)).status_code == 204
    assert (await authenticated_client.get(state_url(product_id))).json()["competitors"] == []


# ─── Evidence ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_evidence_types_and_association(authenticated_client, db_session, monkeypatch):
    project_id, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id)
    base = f"/api/products/{product_id}/competitors/{c['id']}/evidence"
    sources_before = await db_session.scalar(select(func.count(SourceDocument.id)).where(SourceDocument.project_id == UUID(project_id)))

    note = await add_note(authenticated_client, product_id, c["id"])
    assert note["status"] == "completed" and note["char_count"] == len(ZOHO_PAGE)

    monkeypatch.setattr(ExtractionService, "extract_from_url", staticmethod(lambda url, metadata=None: ExtractionResult(ZOHO_PAGE, {"title": "Zoho Books"})))
    page = (await authenticated_client.post(base, data={"evidence_type": "url", "content": "http://93.184.215.14/books"})).json()
    assert page["status"] == "completed" and page["title"] == "Zoho Books"

    def failing(url, metadata=None):
        raise ValueError("Failed to fetch URL: 404")
    monkeypatch.setattr(ExtractionService, "extract_from_url", staticmethod(failing))
    failed = (await authenticated_client.post(base, data={"evidence_type": "url", "content": "http://93.184.215.14/missing"})).json()
    assert failed["status"] == "failed" and "404" in failed["error"]

    monkeypatch.setattr(ExtractionService, "extract_from_pdf", staticmethod(lambda b, metadata=None: ExtractionResult("Zoho brochure text", {})))
    pdf = await authenticated_client.post(base, data={"evidence_type": "pdf"}, files={"file": ("../brochure.pdf", b"%PDF fake", "application/pdf")})
    assert pdf.status_code == 201 and pdf.json()["title"] == "brochure.pdf"

    stored = (await db_session.execute(select(CompetitorEvidence).where(CompetitorEvidence.competitor_id == UUID(c["id"])))).scalars().all()
    assert len(stored) == 4 and all(e.product_id == UUID(product_id) for e in stored)
    # Competitor evidence never becomes one of the project's own product sources.
    sources_after = await db_session.scalar(select(func.count(SourceDocument.id)).where(SourceDocument.project_id == UUID(project_id)))
    assert sources_after == sources_before

    assert (await authenticated_client.delete(f"{base}/{note['id']}")).status_code == 204


@pytest.mark.asyncio
async def test_url_safety_and_social_platforms(authenticated_client, monkeypatch):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id)
    base = f"/api/products/{product_id}/competitors/{c['id']}/evidence"

    for unsafe in ("http://127.0.0.1:8000/api/diagnostics", "http://169.254.169.254/latest/meta-data/", "file:///etc/passwd"):
        assert (await authenticated_client.post(base, data={"evidence_type": "url", "content": unsafe})).status_code == 400

    fetch = AsyncMock()
    monkeypatch.setattr(ExtractionService, "extract_from_url", staticmethod(fetch))
    with patch("app.services.competitor_service.validate_public_url", side_effect=lambda url, **kw: url):
        res = await authenticated_client.post(base, data={"evidence_type": "url", "content": "https://www.linkedin.com/company/zoho"})
    assert res.json()["status"] == "not_fetched" and "social media" in res.json()["error"]
    fetch.assert_not_called()


# ─── Isolation ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_other_users_cannot_touch_competitors(authenticated_client, other_client):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id)
    ev = await add_note(authenticated_client, product_id, c["id"])
    cid = c["id"]

    assert (await other_client.get(state_url(product_id))).status_code == 404
    assert (await other_client.post(f"/api/products/{product_id}/competitors", json={"name": "Y"})).status_code == 404
    assert (await other_client.patch(f"/api/products/{product_id}/competitors/{cid}", json={"notes": "x"})).status_code == 404
    assert (await other_client.delete(f"/api/products/{product_id}/competitors/{cid}")).status_code == 404
    assert (await other_client.post(f"/api/products/{product_id}/competitors/{cid}/evidence", data={"evidence_type": "note", "content": "x"})).status_code == 404
    assert (await other_client.delete(f"/api/products/{product_id}/competitors/{cid}/evidence/{ev['id']}")).status_code == 404
    assert (await other_client.post(f"/api/products/{product_id}/competitors/{cid}/analyze")).status_code == 404
    assert (await other_client.post(f"/api/products/{product_id}/competitor-comparison")).status_code == 404
    assert len((await authenticated_client.get(state_url(product_id))).json()["competitors"][0]["evidence"]) == 1


@pytest.mark.asyncio
async def test_competitors_and_evidence_are_bound_to_their_product(authenticated_client):
    _, product_a = await make_product(authenticated_client)
    _, product_b = await make_product(authenticated_client)
    ca = await add_competitor(authenticated_client, product_a)
    cb = await add_competitor(authenticated_client, product_b, notes="B notes")
    ev_a = await add_note(authenticated_client, product_a, ca["id"])

    # A's competitor cannot be reached through product B, nor A's evidence through B's competitor.
    assert (await authenticated_client.patch(f"/api/products/{product_b}/competitors/{ca['id']}", json={"notes": "x"})).status_code == 404
    assert (await authenticated_client.post(f"/api/products/{product_b}/competitors/{ca['id']}/analyze")).status_code == 404
    assert (await authenticated_client.delete(f"/api/products/{product_b}/competitors/{cb['id']}/evidence/{ev_a['id']}")).status_code == 404
    names_b = [c["name"] for c in (await authenticated_client.get(state_url(product_b))).json()["competitors"]]
    assert names_b == ["Zoho Books"] and "Zoho Books is online" not in str((await authenticated_client.get(state_url(product_b))).json())


# ─── Discovery ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_discovery_only_uses_names_from_product_sources(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    res = (await authenticated_client.post(f"/api/products/{product_id}/competitors/discover")).json()
    assert sorted(res["added"]) == ["Vyapar", "Zoho Books"]
    assert any("not available" in m for m in res["messages"])
    competitors = res["state"]["competitors"]
    assert {c["origin"] for c in competitors} == {"product_sources"}
    assert {c["verification"] for c in competitors} == {"named_in_sources"}
    again = (await authenticated_client.post(f"/api/products/{product_id}/competitors/discover")).json()
    assert again["added"] == []


@pytest.mark.asyncio
async def test_ai_suggestions_are_unverified_until_backed_by_evidence(authenticated_client, monkeypatch):
    _, product_id = await make_product(authenticated_client)
    monkeypatch.setattr(settings, "AI_PROVIDER", "claude")
    suggestions = AsyncMock(return_value={"candidates": [
        {"name": "Refrens", "why_relevant": "Invoicing for freelancers", "website_url": None},
        {"name": "LedgerLeaf", "why_relevant": "our own product", "website_url": None},
    ]})
    with patch("app.services.competitor_intelligence.run_competitor_suggestions", suggestions):
        res = (await authenticated_client.post(f"/api/products/{product_id}/competitors/discover")).json()
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    assert "Refrens" in res["added"] and "LedgerLeaf" not in res["added"]
    refrens = next(c for c in res["state"]["competitors"] if c["name"] == "Refrens")
    assert refrens["origin"] == "ai_suggested" and refrens["verification"] == "unverified"

    await add_note(authenticated_client, product_id, refrens["id"], "Refrens offers invoicing for freelancers.")
    state = (await authenticated_client.get(state_url(product_id))).json()
    assert next(c for c in state["competitors"] if c["name"] == "Refrens")["verification"] == "evidence_backed"


# ─── Analysis ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_no_evidence_means_insufficient_evidence_not_invented_analysis(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id)
    res = (await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")).json()
    assert res["analysis_status"] == "insufficient_evidence"
    assert all(v == "unknown" for v in res["analysis"]["coverage"].values())
    assert "No evidence yet" in res["analysis"]["unknowns"][0]


@pytest.mark.asyncio
async def test_analysis_references_resolve_to_stored_evidence_and_persist(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id, notes="Their ads talk about GST deadlines.")
    ev = await add_note(authenticated_client, product_id, c["id"])
    analyzed = (await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")).json()

    a = analyzed["analysis"]
    assert analyzed["analysis_status"] == "analyzed" and analyzed["last_analyzed_at"]
    assert a["references"]["E1"]["evidence_id"] == ev["id"]
    assert a["references"]["N"]["kind"] == "user_notes"
    for section in ("overview", "positioning", "overlapping_features", "promotion_channels", "content_formats"):
        for f in a[section]:
            assert set(f["refs"]) <= set(a["references"])
    assert a["coverage"]["posting_cadence"] == "unknown" and a["posting_cadence"] == []
    assert "performance" in a["performance_data"]
    assert a["provider"] == "demo"

    reloaded = (await authenticated_client.get(state_url(product_id))).json()["competitors"][0]
    assert reloaded["analysis"] == a


# ─── Comparison + approval ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_comparison_and_approval_flow(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    assert (await authenticated_client.post(f"/api/products/{product_id}/competitor-comparison")).status_code == 409

    c = await add_competitor(authenticated_client, product_id)
    await add_note(authenticated_client, product_id, c["id"])
    await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")
    state = (await authenticated_client.get(state_url(product_id))).json()
    approve_url = f"/api/products/{product_id}/competitor-analysis/approve"
    assert (await authenticated_client.post(approve_url, json={"project_id": project_id, "version": state["version"]})).status_code == 409

    compared = (await authenticated_client.post(f"/api/products/{product_id}/competitor-comparison")).json()
    comp = compared["comparison"]
    assert compared["status"] == "ready_for_review" and not compared["comparison_outdated"]
    assert set(comp) >= {"similarities", "differences", "messaging_gaps", "positioning_opportunities",
                         "promotion_patterns_to_investigate", "evidence_needed"}
    assert comp["competitors"]["C1"]["name"] == "Zoho Books"
    for f in comp["similarities"] + comp["messaging_gaps"]:
        assert set(f["refs"]) <= set(comp["references"])
    assert any("WhatsApp" in f["statement"] for f in comp["differences"])

    stale = await authenticated_client.post(approve_url, json={"project_id": project_id, "version": compared["version"] - 1})
    assert stale.status_code == 409
    approved = (await authenticated_client.post(approve_url, json={"project_id": project_id, "version": compared["version"]})).json()
    assert approved["status"] == "approved" and approved["approved_at"]

    project = (await authenticated_client.get(f"/api/projects/{project_id}")).json()
    stage = next(s for s in project["stages"] if s["stage_type"] == "competitor-analysis")
    assert stage["data"] == {"product_id": product_id, "approved_version": approved["approved_version"]}

    # Any later change re-opens review and marks the comparison outdated.
    await add_note(authenticated_client, product_id, c["id"], "Zoho also runs webinars.")
    after = (await authenticated_client.get(state_url(product_id))).json()
    assert after["status"] == "in_progress" and after["comparison_outdated"] is True


@pytest.mark.asyncio
async def test_approval_requires_a_project_linked_to_the_product(authenticated_client):
    project_a, product_a = await make_product(authenticated_client)
    project_b, _ = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_a)
    await add_note(authenticated_client, product_a, c["id"])
    await authenticated_client.post(f"/api/products/{product_a}/competitors/{c['id']}/analyze")
    compared = (await authenticated_client.post(f"/api/products/{product_a}/competitor-comparison")).json()
    res = await authenticated_client.post(f"/api/products/{product_a}/competitor-analysis/approve",
                                          json={"project_id": project_b, "version": compared["version"]})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_state_survives_a_separate_session(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    c = await add_competitor(authenticated_client, product_id)
    await add_note(authenticated_client, product_id, c["id"])
    analyzed = (await authenticated_client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")).json()
    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as fresh:
        row = await fresh.get(Competitor, UUID(c["id"]))
        assert row.analysis_status == "analyzed" and row.analysis["references"] == analyzed["analysis"]["references"]
