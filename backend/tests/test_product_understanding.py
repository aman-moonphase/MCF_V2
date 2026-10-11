"""Product Understanding API: answers, edits, approval, persistence, relationships, and isolation."""
import uuid
from datetime import timedelta

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models.user import User

LEDGERLEAF = (
    "Product: LedgerLeaf - a bookkeeping app for freelance designers in India. "
    "Features: auto-import of UPI and bank transactions, GST invoice generation, and a client payment tracker. "
    "Pricing: Pro at Rs 299/month. Target users: solo designers and small studios. "
    "Main alternatives people use today: Zoho Books, Vyapar."
)
CARENEST = (
    "Product: CareNest - a medication reminder app for families looking after elderly parents. "
    "Features: pill schedules, missed-dose alerts, and refill tracking. Target users: adult children caring for parents."
)


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def make_project(client, source=LEDGERLEAF, title="Launch campaign"):
    res = await client.post("/api/projects", json={"title": title, "source_type": "Text Idea", "source_reference": source[:100]})
    assert res.status_code == 201
    project_id = res.json()["id"]
    ing = await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": source})
    assert ing.status_code == 200
    return project_id


async def understand(client, project_id):
    res = await client.post(f"/api/projects/{project_id}/product-understanding")
    assert res.status_code == 200, res.text
    return res.json()


@pytest.fixture
async def other_client(db_session):
    user = User(email=f"other-{uuid.uuid4().hex[:8]}@example.com", hashed_password=get_password_hash("x" * 12), is_active=True)
    db_session.add(user)
    await db_session.commit()
    token = create_access_token(subject=str(user.id), expires_delta=timedelta(minutes=30))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ac.headers.update({"Authorization": f"Bearer {token}"})
        yield ac


# ─── Start + workflow placement ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_product_understanding_is_the_stage_after_source_grounding(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    stages = [s["stage_type"] for s in res.json()["stages"]]
    assert stages[:5] == ["source-grounding", "product-understanding", "competitor-analysis", "promotion-strategy", "content-type"]


@pytest.mark.asyncio
async def test_start_builds_profile_and_links_project(authenticated_client):
    project_id = await make_project(authenticated_client)
    assert (await authenticated_client.get(f"/api/projects/{project_id}/product")).json() is None

    product = await understand(authenticated_client, project_id)
    assert product["name"] == "LedgerLeaf"
    assert product["profile"]["key_features"]
    assert product["profile"]["source_references"][0]["source_type"] == "text"
    assert product["understanding_status"] in ("needs_clarification", "ready_for_review")
    assert product["project_ids"] == [project_id]

    project = (await authenticated_client.get(f"/api/projects/{project_id}")).json()
    assert project["product_id"] == product["id"]
    stage = next(s for s in project["stages"] if s["stage_type"] == "product-understanding")
    # The project stores a reference only — never a copy of the profile.
    assert stage["data"] == {"product_id": product["id"]}


@pytest.mark.asyncio
async def test_start_without_sources_is_rejected(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "Empty", "source_type": "Text Idea", "source_reference": " "})
    project_id = res.json()["id"]
    from unittest.mock import AsyncMock, patch
    with patch("app.services.product_service.get_project_source_text", new=AsyncMock(return_value="")):
        res = await authenticated_client.post(f"/api/projects/{project_id}/product-understanding")
    assert res.status_code == 400


# ─── 6. Answers ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_answering_updates_profile_and_is_not_asked_again(authenticated_client):
    project_id = await make_project(authenticated_client)
    product = await understand(authenticated_client, project_id)
    open_qs = [q for q in product["clarification_questions"] if q["status"] == "open"]
    assert open_qs
    target = open_qs[0]

    res = await authenticated_client.post(
        f"/api/products/{product['id']}/clarifications",
        json={"project_id": project_id, "answers": [{"question_id": target["id"], "answer": "Freelancers lose hours reconciling GST by hand."}]},
    )
    assert res.status_code == 200, res.text
    updated = res.json()
    for field in target["fields"]:
        assert updated["profile"][field]
    answered = next(q for q in updated["clarification_questions"] if q["id"] == target["id"])
    assert answered["status"] == "answered" and answered["answer"]
    assert updated["profile_version"] > product["profile_version"]
    # The answered question is never asked again, even after a refresh.
    refreshed = await understand(authenticated_client, project_id)
    asked_for_field = [q for q in refreshed["clarification_questions"] if set(q["fields"]) & set(target["fields"])]
    assert len(asked_for_field) == 1
    # Re-answering a closed question is rejected.
    again = await authenticated_client.post(
        f"/api/products/{product['id']}/clarifications",
        json={"project_id": project_id, "answers": [{"question_id": target["id"], "answer": "again"}]},
    )
    assert again.status_code == 422


@pytest.mark.asyncio
async def test_answers_must_belong_to_this_product(authenticated_client):
    p1 = await make_project(authenticated_client)
    p2 = await make_project(authenticated_client, source="A bookkeeping platform for freelance designers.")
    prod1 = await understand(authenticated_client, p1)
    prod2 = await understand(authenticated_client, p2)
    foreign_q = next(q for q in prod2["clarification_questions"] if q["status"] == "open")

    res = await authenticated_client.post(
        f"/api/products/{prod1['id']}/clarifications",
        json={"project_id": p1, "answers": [{"question_id": foreign_q["id"], "answer": "x"}]},
    )
    assert res.status_code == 422
    # A project that is not linked to the product cannot be used to answer for it.
    res = await authenticated_client.post(
        f"/api/products/{prod2['id']}/clarifications",
        json={"project_id": p1, "answers": [{"question_id": foreign_q["id"], "answer": "x"}]},
    )
    assert res.status_code == 400
    res = await authenticated_client.post(
        f"/api/products/{prod2['id']}/clarifications",
        json={"project_id": p2, "answers": [{"question_id": foreign_q["id"], "answer": "   "}]},
    )
    assert res.status_code == 422


# ─── 7. Edits ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_profile_edits_are_validated_and_preserved(authenticated_client):
    project_id = await make_project(authenticated_client)
    product = await understand(authenticated_client, project_id)
    url = f"/api/products/{product['id']}/profile"

    res = await authenticated_client.patch(url, json={"profile": {"value_proposition": "Bookkeeping that designers finish in minutes", "use_cases": ["Quarterly GST filing"]}})
    assert res.status_code == 200
    edited = res.json()
    assert edited["profile"]["value_proposition"] == "Bookkeeping that designers finish in minutes"
    assert "value_proposition" in edited["edited_fields"]
    assert "value_proposition" not in edited["profile"]["missing_fields"]

    assert (await authenticated_client.patch(url, json={"profile": {"brand_colour": "blue"}})).status_code == 422
    assert (await authenticated_client.patch(url, json={"profile": {"key_features": "not a list"}})).status_code == 422

    refreshed = await understand(authenticated_client, project_id)
    assert refreshed["profile"]["value_proposition"] == "Bookkeeping that designers finish in minutes"


# ─── 8. Approval ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_is_version_checked_and_gates_downstream_context(authenticated_client):
    project_id = await make_project(authenticated_client)
    product = await understand(authenticated_client, project_id)
    approved_url = f"/api/projects/{project_id}/product/approved-profile"
    assert (await authenticated_client.get(approved_url)).status_code == 409

    stale = await authenticated_client.post(
        f"/api/products/{product['id']}/approve", json={"project_id": project_id, "profile_version": product["profile_version"] - 1}
    )
    assert stale.status_code == 409

    res = await authenticated_client.post(
        f"/api/products/{product['id']}/approve", json={"project_id": project_id, "profile_version": product["profile_version"]}
    )
    assert res.status_code == 200
    approved = res.json()
    assert approved["understanding_status"] == "approved" and approved["approved_at"]

    context = (await authenticated_client.get(approved_url)).json()
    assert context["product_id"] == product["id"] and context["profile"]["name"] == "LedgerLeaf"

    project = (await authenticated_client.get(f"/api/projects/{project_id}")).json()
    stage = next(s for s in project["stages"] if s["stage_type"] == "product-understanding")
    assert stage["data"]["approved_version"] == approved["approved_version"]

    # Editing an approved profile requires approving again.
    edited = await authenticated_client.patch(f"/api/products/{product['id']}/profile", json={"profile": {"positioning": "Designer-first bookkeeping"}})
    assert edited.json()["understanding_status"] != "approved"
    assert (await authenticated_client.get(approved_url)).status_code == 409


# ─── 9. Persistence ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_understanding_persists_across_sessions(authenticated_client):
    project_id = await make_project(authenticated_client)
    product = await understand(authenticated_client, project_id)
    await authenticated_client.post(
        f"/api/products/{product['id']}/approve", json={"project_id": project_id, "profile_version": product["profile_version"]}
    )
    # A completely separate session/connection reads the same state back from PostgreSQL.
    from uuid import UUID
    from tests.conftest import TestingSessionLocal
    from app.models.product import Product
    async with TestingSessionLocal() as fresh:
        row = await fresh.get(Product, UUID(product["id"]))
        assert row.profile["name"] == "LedgerLeaf"
        assert row.understanding_status == "approved"
        assert row.approved_version == product["profile_version"]
        assert [q["id"] for q in row.clarification_questions] == [q["id"] for q in product["clarification_questions"]]

    stored = (await authenticated_client.get(f"/api/projects/{project_id}/product")).json()
    assert stored["profile"] == product["profile"]
    assert stored["clarification_questions"] == product["clarification_questions"]
    assert stored["understanding_status"] == "approved"


# ─── 10. Product ↔ Project relationship ─────────────────────────────────────

@pytest.mark.asyncio
async def test_one_product_is_reused_by_many_projects(authenticated_client):
    p1 = await make_project(authenticated_client)
    product = await understand(authenticated_client, p1)
    res = await authenticated_client.post("/api/projects", json={"title": "Second campaign", "source_type": "Text Idea", "source_reference": "x"})
    p2 = res.json()["id"]

    linked = await authenticated_client.put(f"/api/projects/{p2}/product", json={"product_id": product["id"]})
    assert linked.status_code == 200
    assert set(linked.json()["project_ids"]) == {p1, p2}
    assert (await authenticated_client.get(f"/api/projects/{p2}/product")).json()["id"] == product["id"]
    assert len([p for p in (await authenticated_client.get("/api/products")).json() if p["id"] == product["id"]]) == 1


# ─── 11. User isolation ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_other_users_cannot_access_a_product(authenticated_client, other_client):
    project_id = await make_project(authenticated_client)
    product = await understand(authenticated_client, project_id)
    pid = product["id"]
    q = product["clarification_questions"][0]["id"] if product["clarification_questions"] else "x"

    assert (await other_client.get(f"/api/products/{pid}")).status_code == 404
    assert (await other_client.patch(f"/api/products/{pid}/profile", json={"profile": {"name": "Hacked"}})).status_code == 404
    assert (await other_client.post(f"/api/products/{pid}/approve", json={"project_id": project_id, "profile_version": 1})).status_code == 404
    assert (await other_client.post(f"/api/products/{pid}/clarifications", json={"project_id": project_id, "answers": [{"question_id": q, "answer": "x"}]})).status_code == 404
    assert (await other_client.post(f"/api/projects/{project_id}/product-understanding")).status_code == 404
    assert (await other_client.get(f"/api/projects/{project_id}/product")).status_code == 404
    assert (await other_client.get(f"/api/projects/{project_id}/product/approved-profile")).status_code == 404
    assert all(p["id"] != pid for p in (await other_client.get("/api/products")).json())

    # Another user's product cannot be linked into your own project either.
    own = await other_client.post("/api/projects", json={"title": "mine", "source_type": "Text Idea", "source_reference": "x"})
    res = await other_client.put(f"/api/projects/{own.json()['id']}/product", json={"product_id": pid})
    assert res.status_code == 404
    assert (await authenticated_client.get(f"/api/products/{pid}")).json()["name"] == "LedgerLeaf"


# ─── 12. No cross-project leakage ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_each_project_only_uses_its_own_sources(authenticated_client):
    ledger = await understand(authenticated_client, await make_project(authenticated_client, LEDGERLEAF))
    care = await understand(authenticated_client, await make_project(authenticated_client, CARENEST, title="Care launch"))
    assert ledger["id"] != care["id"]
    assert care["name"] == "CareNest" and "LedgerLeaf" not in str(care["profile"])
    assert "CareNest" not in str(ledger["profile"]) and "Zoho" not in str(care["profile"])


# ─── 13. Product name extraction regressions ────────────────────────────────

@pytest.mark.asyncio
async def test_extracts_product_name_from_preamble_focusflow_description(authenticated_client):
    """Extracts FocusFlow from sentences like 'Create a test project for FocusFlow, a lightweight...'"""
    source = (
        "Create a test project for FocusFlow, a lightweight scheduling tool for independent music tutors.\n"
        "Features:\n"
        "- Lesson booking links\n"
        "- Reminder emails 24 hours before lessons\n"
        "- Attendance notes\n\n"
        "Target audience: Independent music tutors.\n"
        "Goal: Promote the product through LinkedIn social posts."
    )
    project_id = await make_project(authenticated_client, source=source, title="FocusFlow Launch")
    product = await understand(authenticated_client, project_id)

    assert product["name"] == "FocusFlow"
    assert product["profile"]["name"] == "FocusFlow"
    assert product["profile"]["category"] == "lightweight scheduling tool"
    assert product["profile"]["target_audience"] == "Independent music tutors"
    assert product["profile"]["key_features"] == [
        "Lesson booking links",
        "Reminder emails 24 hours before lessons",
        "Attendance notes",
    ]
    # Genuinely missing fields remain uninvented
    assert product["profile"]["business_model"] is None
    assert product["profile"]["differentiators"] == []
    assert product["profile"]["known_competitors"] == []


@pytest.mark.asyncio
async def test_extracts_product_name_from_appositive_description(authenticated_client):
    """Extracts name from appositive opening 'FocusFlow, a lightweight scheduling tool...'"""
    source = (
        "FocusFlow, a lightweight scheduling tool for independent music tutors.\n"
        "Features:\n"
        "- Lesson booking links"
    )
    project_id = await make_project(authenticated_client, source=source, title="Appositive Test")
    product = await understand(authenticated_client, project_id)

    assert product["name"] == "FocusFlow"
    assert product["profile"]["name"] == "FocusFlow"


@pytest.mark.asyncio
async def test_preserves_genuinely_missing_product_name_without_inventing(authenticated_client):
    """When no product name is present, profile name remains None and is not invented."""
    source = (
        "A lightweight scheduling tool for independent music tutors.\n"
        "Features:\n"
        "- Lesson booking links\n"
        "- Reminder emails 24 hours before lessons"
    )
    project_id = await make_project(authenticated_client, source=source, title="Generic Scheduler")
    product = await understand(authenticated_client, project_id)

    # Name is not extracted/invented from generic prose
    assert product["profile"]["name"] is None
    assert "name" in product["profile"]["missing_fields"]
    # Clarification question is asked for the missing name
    assert any("name" in q.get("fields", []) for q in product["clarification_questions"])


def test_build_demo_profile_name_extraction_unit():
    """Unit test covering multiple variations of product name extraction and genuinely missing cases."""
    from app.ai.generation_context import generation_context
    from app.ai.providers.demo_product import build_demo_profile

    cases = [
        ("Create a test project for FocusFlow, a lightweight scheduling tool for music tutors.", "FocusFlow"),
        ("FocusFlow, a lightweight scheduling tool for independent music tutors.", "FocusFlow"),
        ("FocusFlow is a lightweight scheduling tool for music tutors.", "FocusFlow"),
        ("FocusFlow - a lightweight scheduling tool for music tutors.", "FocusFlow"),
        ("Project for FocusFlow: a lightweight scheduling tool for music tutors.", "FocusFlow"),
        ("We are launching FocusFlow, a lightweight scheduling tool for tutors.", "FocusFlow"),
        ("A lightweight scheduling tool for independent music tutors.", None),
        ("This is a tool for scheduling meetings.", None),
        ("Features:\n- Lesson booking links", None),
        ("In 2024, our team started building software.", None),
        ("We need marketing content for our scheduling software.", None),
    ]

    for src, expected_name in cases:
        with generation_context({"input_text": src}, "product-understanding"):
            profile = build_demo_profile("")
            assert profile.get("name") == expected_name, f"Failed for source: {src} -> got {profile.get('name')}"
