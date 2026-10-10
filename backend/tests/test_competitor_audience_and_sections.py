"""Regression (manual StudioDesk / Momoyoga test):
1. explicit audience statements on the competitor's website ("we help yoga teachers and studios ...") were
   reported as an unknown target audience;
2. section names ("Target audience · ... · Opportunities for our product") were rendered inside the
   unknown / evidence-gaps list, because `unknowns` mixed section-level notes with real unknown items.
"""
from unittest.mock import patch

import pytest

from app.ai.competitor_grounding import ground_analysis
from app.ai.competitor_schemas import FINDING_SECTIONS, SECTION_LABELS
from app.ai.graphs.competitor_graph import run_competitor_analysis
from tests.test_competitor_analysis import add_competitor, add_note, make_product

PRODUCT = {"name": "StudioDesk", "key_features": ["Class booking links", "Attendance tracking"]}
MOMOYOGA = (
    "The home for every yoga teacher and studio. "
    "At Momoyoga, we help yoga teachers and studios build successful, sustainable businesses while making it easier for yogis to book classes. "
    "Create a seamless booking experience for students. "
    "\"Highly recommend it for any yoga teacher or studio!\""
)


async def analyse(*texts, product=PRODUCT):
    items = [{"label": f"E{i}", "text": t} for i, t in enumerate(texts, start=1)]
    state = {"prompt_context": [], "allowed_refs": [i["label"] for i in items], "corpus": "\n".join(texts),
             "evidence_count": len(items), "demo_input": {"product": product, "competitor": {"name": "Momoyoga"}, "items": items}}
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_competitor_analysis(state)


def audiences(analysis):
    return [f["statement"].split('"')[1] for f in analysis["target_audience"]]


# ─── 1. Target audience ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_explicit_audience_is_observed_and_cited():
    a = await analyse(MOMOYOGA)
    assert a["coverage"]["target_audience"] == "observed"
    assert "target_audience" not in a["unknown_sections"]
    assert audiences(a)[0] == "yoga teachers and studios"
    first = a["target_audience"][0]
    assert first["status"] == "observed" and first["refs"] == ["E1"]
    assert "we help yoga teachers and studios" in first["statement"]  # the supporting sentence is quoted


@pytest.mark.asyncio
async def test_audience_is_only_what_the_evidence_states():
    a = await analyse(MOMOYOGA)
    found = " ".join(audiences(a)).lower()
    assert "students" not in found          # their customers' customers, from "an experience for students"
    assert "any yoga teacher" not in found  # a customer testimonial is not the company's stated audience
    assert "yoga teacher and studio" not in audiences(a)  # singular variant merged into the plural
    for detail in ("india", "europe", "women", "aged", "beginner", "enterprise"):
        assert detail not in str(a["target_audience"]).lower()


@pytest.mark.asyncio
async def test_no_audience_statement_stays_unknown():
    a = await analyse("Online booking and payments in one place. Get started for free.")
    assert a["target_audience"] == []
    assert a["coverage"]["target_audience"] == "unknown" and "target_audience" in a["unknown_sections"]


# ─── 2. Section headings are never unknown items ────────────────────────────

@pytest.mark.asyncio
async def test_unknown_items_never_contain_section_headings():
    a = await analyse(MOMOYOGA)
    labels = {label.lower() for label in SECTION_LABELS.values()}
    for item in a["unknowns"]:
        assert item.strip().lower() not in labels
        assert not any(item.lower().startswith(label + ":") for label in labels)
        assert "not supported by the available evidence" not in item
    assert set(a["unknown_sections"]) <= set(FINDING_SECTIONS) | {"content_examples"}


def test_grounding_lists_empty_sections_separately_from_items():
    out = ground_analysis({"overview": [{"statement": "Momoyoga is yoga software", "status": "observed", "refs": ["E1"]}]},
                          ["E1"], "Momoyoga is yoga software", evidence_count=1)
    assert out["unknowns"] == []
    assert "opportunities_for_us" in out["unknown_sections"] and "overview" not in out["unknown_sections"]


@pytest.mark.asyncio
async def test_empty_opportunities_are_an_empty_section_not_an_unknown_item(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    competitor = await add_competitor(authenticated_client, product_id, name="Momoyoga")
    await add_note(authenticated_client, product_id, competitor["id"], text=MOMOYOGA)
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert res.status_code == 200, res.text
    analysis = res.json()["analysis"]
    assert analysis["opportunities_for_us"] == []
    assert analysis["coverage"]["opportunities_for_us"] == "unknown"
    assert "opportunities_for_us" in analysis["unknown_sections"]
    assert not any("opportunities for our product" in u.lower() for u in analysis["unknowns"])
    assert analysis["target_audience"][0]["refs"] == ["E1"]
