"""Regression: a structured brief with heading-style labels and bullet lists (the manual StudioDesk test) must be
fully extracted by Product Understanding instead of producing an empty profile and redundant questions.

The full brief is stored on ingestion and reached the workflow; the Demo extractor only understood
"Label: value" on one line, so headings ("Features:" + bullets on the next lines) were lost.
"""
import re
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.ai.graphs.product_understanding_graph import run_product_understanding
from app.core.config import settings
from app.models.source import SourceDocument

# Exactly as a browser form submits a textarea (CRLF line endings), as stored for the failing project.
STUDIODESK = (
    "Product: StudioDesk\r\n\r\nDescription:\r\nStudioDesk is a booking and invoicing app for independent yoga teachers.\r\n\r\n"
    "Features:\r\n- Class booking links\r\n- Automatic payment reminders\r\n- Attendance tracking\r\n- Offline attendance check-in\r\n\r\n"
    "Target users:\r\nIndependent yoga teachers who teach in rented studios.\r\n\r\n"
    "Value proposition:\r\nSpend time teaching, not chasing payments.\r\n\r\n"
    "Differentiator:\r\nOffline attendance check-in helps teachers manage attendance even without an internet connection."
)
# The same brief as pasted in chat: "*" bullets and blank lines inside the feature block.
STUDIODESK_STARS = STUDIODESK.replace("\r\n", "\n").replace("Features:\n- ", "Features:\n\n* ").replace("\n- ", "\n* ")
STUDIODESK_PROSE = (
    "StudioDesk is a booking and invoicing app for independent yoga teachers who teach in rented studios. "
    "It includes class booking links, automatic payment reminders, attendance tracking and offline attendance check-in. "
    "Unlike typical studio software, StudioDesk keeps attendance check-in working without an internet connection. "
    "With StudioDesk, teachers spend their time teaching instead of chasing payments."
)
INCOMPLETE = "Product: PotterPal\n\nDescription:\nPotterPal is an app for ceramic studios."
FEATURES = ["Class booking links", "Automatic payment reminders", "Attendance tracking", "Offline attendance check-in"]


async def understand_text(source):
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_product_understanding(source)


def asked(result):
    return {f for q in result["questions"] for f in q["fields"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("source", [STUDIODESK, STUDIODESK_STARS], ids=["dash-bullets-crlf", "star-bullets"])
async def test_labelled_studiodesk_brief_is_fully_extracted(source):
    result = await understand_text(source)
    p = result["profile"]
    assert p["name"] == "StudioDesk"
    assert p["description"] == "StudioDesk is a booking and invoicing app for independent yoga teachers."
    assert p["category"] == "booking and invoicing app"
    assert p["target_audience"].rstrip(".") == "Independent yoga teachers who teach in rented studios"
    assert p["primary_users"] == ["Independent yoga teachers who teach in rented studios"]
    assert p["key_features"] == FEATURES
    assert p["value_proposition"] == "Spend time teaching, not chasing payments."
    assert p["differentiators"] == ["Offline attendance check-in helps teachers manage attendance even without an internet "
                                    "connection"]
    # Only what the brief genuinely lacks is asked about.
    assert asked(result) <= {"problem_solved", "business_model"}
    assert not asked(result) & {"name", "description", "category", "target_audience", "key_features", "value_proposition",
                                "differentiators"}


@pytest.mark.asyncio
async def test_free_text_equivalent_without_labels():
    result = await understand_text(STUDIODESK_PROSE)
    p = result["profile"]
    assert p["name"] == "StudioDesk"
    assert p["category"] == "booking and invoicing app"
    assert p["target_audience"] == "independent yoga teachers who teach in rented studios"
    assert p["key_features"] == FEATURES
    assert p["differentiators"] == ["Unlike typical studio software, StudioDesk keeps attendance check-in working without an "
                                    "internet connection"]
    assert p["value_proposition"] == "With StudioDesk, teachers spend their time teaching instead of chasing payments"
    assert not asked(result) & {"name", "category", "target_audience", "key_features", "value_proposition"}


@pytest.mark.asyncio
async def test_incomplete_source_gets_clarification_questions_and_no_invented_facts():
    result = await understand_text(INCOMPLETE)
    p = result["profile"]
    assert p["name"] == "PotterPal" and p["description"] == "PotterPal is an app for ceramic studios."
    assert p["target_audience"] == "ceramic studios"
    for field in ("problem_solved", "value_proposition", "business_model", "positioning", "market_geography"):
        assert p[field] is None, field
    assert p["key_features"] == [] and p["differentiators"] == [] and p["key_benefits"] == []
    assert {"problem_solved", "key_features", "value_proposition"} <= asked(result)
    assert "target_audience" not in asked(result)


@pytest.mark.asyncio
async def test_no_fabricated_facts_in_the_studiodesk_profile():
    p = (await understand_text(STUDIODESK))["profile"]
    source = re.sub(r"\s+", " ", STUDIODESK).lower()
    for field, value in p.items():
        for item in (value if isinstance(value, list) else [value]):
            if item:
                assert re.sub(r"\s+", " ", item).lower().rstrip(".") in source, (field, item)
    for field in ("problem_solved", "business_model", "market_geography", "website_url", "positioning"):
        assert p[field] is None, field
    assert p["key_benefits"] == [] and p["known_competitors"] == []


# ─── Through the API: ingestion → storage → Product Understanding → persisted profile ───────────────────

@pytest.fixture
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def create_from_composer(client, brief, title):
    """What the Composer does: a project titled from the idea, then the full text ingested as its source."""
    res = await client.post("/api/projects", json={"title": title, "source_type": "Text Idea", "source_reference": brief[:500]})
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]
    ing = await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": brief})
    assert ing.status_code == 200, ing.text
    return project_id


@pytest.mark.asyncio
async def test_full_source_propagates_from_ingestion_to_the_profile(authenticated_client, db_session, demo_mode):
    project_id = await create_from_composer(authenticated_client, STUDIODESK, "Idea: Product: StudioDesk\n\nDescripti...")
    stored = (await db_session.execute(select(SourceDocument).where(SourceDocument.project_id == project_id))).scalar_one()
    assert "Offline attendance check-in helps teachers" in stored.extracted_text  # the last line of the brief is stored

    res = await authenticated_client.post(f"/api/projects/{project_id}/product-understanding")
    assert res.status_code == 200, res.text
    product = res.json()
    p = product["profile"]
    assert product["name"] == "StudioDesk" and product["understanding_status"] == "needs_clarification"
    assert p["description"] == "StudioDesk is a booking and invoicing app for independent yoga teachers."
    assert p["key_features"] == FEATURES
    assert p["value_proposition"] == "Spend time teaching, not chasing payments."
    assert p["source_references"][0]["source_id"] == str(stored.id)
    assert {f for q in product["clarification_questions"] for f in q["fields"]} <= {"problem_solved", "business_model"}

    # Re-analyzing a project whose earlier profile was wrong replaces the wrong values with extracted ones.
    again = (await authenticated_client.post(f"/api/projects/{project_id}/product-understanding")).json()
    assert again["profile"]["key_features"] == FEATURES and again["profile_version"] == product["profile_version"] + 1


@pytest.mark.asyncio
async def test_projects_do_not_share_extracted_facts(authenticated_client, demo_mode):
    studio = await create_from_composer(authenticated_client, STUDIODESK, "StudioDesk")
    potter = await create_from_composer(authenticated_client, INCOMPLETE, "PotterPal")
    a = (await authenticated_client.post(f"/api/projects/{studio}/product-understanding")).json()
    b = (await authenticated_client.post(f"/api/projects/{potter}/product-understanding")).json()
    assert a["id"] != b["id"] and b["name"] == "PotterPal"
    assert "yoga" not in str(b["profile"]).lower() and "studiodesk" not in str(b["profile"]).lower()
    assert "potterpal" not in str(a["profile"]).lower() and "ceramic" not in str(a["profile"]).lower()
    assert b["profile"]["key_features"] == []
