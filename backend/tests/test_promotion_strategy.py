"""Promotion Strategy API: prerequisites, limited evidence, competitor influence, edit/approve, persistence,
isolation, and the Content Type integration."""
import uuid
from datetime import timedelta
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.promotion_strategy import PromotionStrategy
from app.models.user import User

SOURCE = (
    "Product: LedgerLeaf - a bookkeeping app for freelance designers in India. "
    "Features: GST invoice generation, expense categorisation, quarterly tax reminders, and a client payment tracker. "
    "Target users: solo designers and small studios. "
    "Value proposition: bookkeeping designers finish in minutes. "
    "Main alternatives people use today: Zoho Books, Vyapar. "
    "Differentiator: WhatsApp invoice sharing."
)
ZOHO_NOTES = "Zoho Books is online accounting software for small businesses. Create GST invoices in one place. Follow us on LinkedIn."


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def make_product(client):
    res = await client.post("/api/projects", json={"title": "LedgerLeaf launch", "source_type": "Text Idea", "source_reference": "LedgerLeaf"})
    project_id = res.json()["id"]
    await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": SOURCE})
    product = (await client.post(f"/api/projects/{project_id}/product-understanding")).json()
    await client.post(f"/api/products/{product['id']}/approve", json={"project_id": project_id, "profile_version": product["profile_version"]})
    return project_id, product["id"]


async def approve_competitors(client, project_id, product_id, with_evidence=True):
    if with_evidence:
        c = (await client.post(f"/api/products/{product_id}/competitors", json={"name": "Zoho Books"})).json()
        await client.post(f"/api/products/{product_id}/competitors/{c['id']}/evidence", data={"evidence_type": "note", "content": ZOHO_NOTES})
        await client.post(f"/api/products/{product_id}/competitors/{c['id']}/analyze")
        state = (await client.post(f"/api/products/{product_id}/competitor-comparison")).json()
    else:
        state = (await client.get(f"/api/products/{product_id}/competitor-analysis")).json()
    res = await client.post(f"/api/products/{product_id}/competitor-analysis/approve",
                            json={"project_id": project_id, "version": state["version"], "limited_evidence": not with_evidence})
    assert res.status_code == 200, res.text
    return res.json()


def url(product_id, suffix=""):
    return f"/api/products/{product_id}/promotion-strategy{suffix}"


async def generate(client, product_id):
    res = await client.post(url(product_id))
    assert res.status_code == 200, res.text
    return res.json()


async def approve(client, project_id, product_id, version):
    return await client.post(url(product_id, "/approve"), json={"project_id": project_id, "version": version})


def groundings(s):
    yield from (s["executive_summary"]["grounding"], s["audience"]["grounding"], s["content_direction"]["grounding"], s["cadence"]["grounding"])
    for key in ("content_pillars", "channels", "roadmap", "measurement"):
        for item in s[key]:
            yield item["grounding"]


@pytest.fixture
async def other_client(db_session):
    user = User(email=f"strat-{uuid.uuid4().hex[:8]}@example.com", hashed_password=get_password_hash("x" * 12), is_active=True)
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(subject=str(user.id), expires_delta=timedelta(minutes=30))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac


# ─── Workflow + prerequisites ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_stage_order(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    stages = [s["stage_type"] for s in res.json()["stages"]]
    i = stages.index("promotion-strategy")
    assert stages[i - 1] == "competitor-analysis" and stages[i + 1] == "content-type"


@pytest.mark.asyncio
async def test_requires_approved_competitor_analysis(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    state = (await authenticated_client.get(url(product_id))).json()
    assert state["prerequisites_met"] is False and "Competitor Analysis" in state["prerequisite_problem"]
    assert state["status"] == "not_generated"
    assert (await authenticated_client.post(url(product_id))).status_code == 409


@pytest.mark.asyncio
async def test_limited_evidence_needs_explicit_approval(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    state = (await authenticated_client.get(f"/api/products/{product_id}/competitor-analysis")).json()
    implicit = await authenticated_client.post(f"/api/products/{product_id}/competitor-analysis/approve",
                                               json={"project_id": project_id, "version": state["version"]})
    assert implicit.status_code == 409 and "limited evidence" in implicit.json()["detail"]

    approved = await approve_competitors(authenticated_client, project_id, product_id, with_evidence=False)
    assert approved["status"] == "approved" and approved["limited_evidence"] is True

    s = await generate(authenticated_client, product_id)
    assert s["limited_evidence"] is True
    assert s["strategy"]["limitations"][0].startswith("Competitor Analysis was approved with limited evidence")
    assert all(g["basis"] not in ("competitor_observed", "evidence_inferred") for g in groundings(s["strategy"]))


# ─── Competitor intelligence matters ────────────────────────────────────────

@pytest.mark.asyncio
async def test_strategy_uses_competitor_and_profile_context(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate(authenticated_client, product_id)
    strategy = s["strategy"]

    assert s["basis"]["competitors"] == ["Zoho Books"] and s["basis"]["limited_evidence"] is False
    assert "LedgerLeaf" in strategy["executive_summary"]["positioning"]
    bases = {g["basis"] for g in groundings(strategy)}
    assert {"competitor_observed", "product_profile", "hypothesis"} <= bases
    linkedin = next(c for c in strategy["channels"] if c["channel"] == "LinkedIn")
    assert linkedin["grounding"]["basis"] == "competitor_observed" and linkedin["grounding"]["refs"]
    for g in groundings(strategy):
        for ref in g["refs"]:
            assert ref.startswith("profile:") or ref.startswith("C1:")
    assert strategy["cadence"]["is_hypothesis"] is True
    assert "Vyapar" not in str(strategy["channels"])  # no invented competitor activity


# ─── Edit / approve / version ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_approve_and_version_behaviour(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate(authenticated_client, product_id)

    assert (await approve(authenticated_client, project_id, product_id, s["version"] - 1)).status_code == 409
    approved = (await approve(authenticated_client, project_id, product_id, s["version"])).json()
    assert approved["status"] == "approved" and approved["approved_at"]
    project = (await authenticated_client.get(f"/api/projects/{project_id}")).json()
    assert next(st for st in project["stages"] if st["stage_type"] == "promotion-strategy")["data"] == {
        "product_id": product_id, "approved_version": approved["version"]}

    cadence = {**approved["strategy"]["cadence"], "frequency": "1 carousel per week"}
    edited = await authenticated_client.patch(url(product_id), json={"strategy": {"cadence": cadence}})
    assert edited.status_code == 200
    e = edited.json()
    assert e["version"] == approved["version"] + 1 and e["status"] == "draft"   # edits revoke approval
    assert e["strategy"]["cadence"]["frequency"] == "1 carousel per week" and e["edited_sections"] == ["cadence"]

    bad_type = {**e["strategy"]["content_direction"], "primary_content_type": "Podcast"}
    assert (await authenticated_client.patch(url(product_id), json={"strategy": {"content_direction": bad_type}})).status_code == 422
    assert (await authenticated_client.patch(url(product_id), json={"strategy": {"brand_colours": {}}})).status_code == 422
    assert (await approve(authenticated_client, project_id, product_id, e["version"])).status_code == 200


@pytest.mark.asyncio
async def test_upstream_changes_make_the_strategy_stale(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id, with_evidence=False)
    s = await generate(authenticated_client, product_id)
    await authenticated_client.post(f"/api/products/{product_id}/competitors", json={"name": "Vyapar"})
    state = (await authenticated_client.get(url(product_id))).json()
    assert state["stale"] is True and state["prerequisites_met"] is False
    assert (await approve(authenticated_client, project_id, product_id, s["version"])).status_code == 409


@pytest.mark.asyncio
async def test_strategy_persists(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate(authenticated_client, product_id)
    await approve(authenticated_client, project_id, product_id, s["version"])
    from tests.conftest import TestingSessionLocal
    from sqlalchemy import select
    async with TestingSessionLocal() as fresh:
        row = (await fresh.execute(select(PromotionStrategy).where(PromotionStrategy.product_id == UUID(product_id)))).scalar_one()
        assert row.status == "approved" and row.approved_version == s["version"]
        assert row.strategy == s["strategy"]


# ─── Isolation ──────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_other_users_cannot_access_the_strategy(authenticated_client, other_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate(authenticated_client, product_id)
    assert (await other_client.get(url(product_id))).status_code == 404
    assert (await other_client.post(url(product_id))).status_code == 404
    assert (await other_client.patch(url(product_id), json={"strategy": {}})).status_code == 404
    assert (await approve(other_client, project_id, product_id, s["version"])).status_code == 404
    assert (await authenticated_client.get(url(product_id))).json()["status"] == "draft"


@pytest.mark.asyncio
async def test_strategies_do_not_leak_between_products(authenticated_client):
    project_a, product_a = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_a, product_a)
    res = await authenticated_client.post("/api/projects", json={"title": "Care", "source_type": "Text Idea", "source_reference": "c"})
    project_b = res.json()["id"]
    await authenticated_client.post(f"/api/projects/{project_b}/sources/ingest", data={"source_type": "text", "content":
        "Product: CareNest - a medication reminder app for families. Features: pill schedules, missed-dose alerts, and refill tracking. "
        "Target users: adult children caring for parents. Differentiator: no login for parents."})
    prod_b = (await authenticated_client.post(f"/api/projects/{project_b}/product-understanding")).json()
    await authenticated_client.post(f"/api/products/{prod_b['id']}/approve", json={"project_id": project_b, "profile_version": prod_b["profile_version"]})
    await approve_competitors(authenticated_client, project_b, prod_b["id"], with_evidence=False)

    a = (await generate(authenticated_client, product_a))["strategy"]
    b = (await generate(authenticated_client, prod_b["id"]))["strategy"]
    assert "CareNest" not in str(a) and "Zoho" not in str(b) and "LedgerLeaf" not in str(b)
    # Approval must go through a project linked to the product.
    s_b = (await authenticated_client.get(url(prod_b["id"]))).json()
    assert (await approve(authenticated_client, project_a, prod_b["id"], s_b["version"])).status_code == 400


# ─── Content Type integration ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_content_type_follows_the_approved_strategy(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate(authenticated_client, product_id)
    stage_url = f"/api/projects/{project_id}/stages/content-type"

    # Before approval: no recommendation, and no content type can be approved.
    assert (await authenticated_client.post("/api/ai/content-type", json={"project_id": project_id})).status_code == 409
    early = await authenticated_client.patch(stage_url, json={"status": "Completed", "data": {"approved_type": "Carousel"}})
    assert early.status_code == 409

    await approve(authenticated_client, project_id, product_id, s["version"])
    primary = s["strategy"]["content_direction"]["primary_content_type"]
    rec = (await authenticated_client.post("/api/ai/content-type", json={"project_id": project_id})).json()
    assert rec["from_strategy"] is True and rec["recommendation"]["recommendedType"] == primary
    assert rec["recommendation"]["alternatives"] == s["strategy"]["content_direction"]["alternatives"]

    follow = (await authenticated_client.patch(stage_url, json={"status": "Completed", "data": {"approved_type": primary}})).json()
    assert follow["data"]["overrides_strategy"] is False and follow["data"]["strategy_recommended_type"] == primary

    other = "Article" if primary != "Article" else "Video"
    override = (await authenticated_client.patch(stage_url, json={"status": "Completed", "data": {"approved_type": other}})).json()
    assert override["data"]["approved_type"] == other and override["data"]["overrides_strategy"] is True
    assert (await authenticated_client.patch(stage_url, json={"data": {"approved_type": "Reel"}})).status_code == 422

    # Downstream generation is then constrained to the approved type.
    sel = await authenticated_client.post("/api/ai/content-selection", json={"project_id": project_id})
    assert sel.status_code == 200
    assert {o["content_type"] for o in sel.json()["opportunities"]} == {other}


@pytest.mark.asyncio
async def test_projects_outside_the_product_workflow_are_unchanged(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "Legacy-style", "source_type": "Text Idea", "source_reference": "x"})
    project_id = res.json()["id"]
    await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": SOURCE})
    rec = await authenticated_client.post("/api/ai/content-type", json={"project_id": project_id})
    assert rec.status_code == 200 and "from_strategy" not in rec.json()
    ok = await authenticated_client.patch(f"/api/projects/{project_id}/stages/content-type",
                                          json={"status": "Completed", "data": {"approved_type": "Carousel"}})
    assert ok.status_code == 200 and "overrides_strategy" not in ok.json()["data"]
