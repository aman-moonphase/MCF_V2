"""Regression (manual StudioDesk / Momoyoga test): "The supplied evidence does not mention X" was listed under
"Opportunities for our product". Absence from the supplied evidence does not show the competitor lacks X, so
such cases are unknowns / evidence gaps (optionally a labelled hypothesis), never opportunities or weaknesses.
"""
from unittest.mock import patch

import pytest

from app.ai.competitor_grounding import EVIDENCE_GAP_PREFIX, ground_analysis
from app.ai.graphs.competitor_graph import run_competitor_analysis
from tests.test_competitor_analysis import add_competitor, add_note, make_product

STUDIODESK = {
    "name": "StudioDesk",
    "key_features": ["Class booking links", "Automatic payment reminders", "Attendance tracking", "Offline attendance check-in"],
    "differentiators": ["Offline attendance check-in helps teachers manage attendance even without an internet connection"],
}
HOMEPAGE = ("Momoyoga is all-in-one yoga studio management software for class scheduling, bookings, payments, and online "
            "teaching. The only yoga dedicated platform out there.")


async def analyse(*texts, profile=STUDIODESK):
    items = [{"label": f"E{i}", "text": t} for i, t in enumerate(texts, start=1)]
    state = {"prompt_context": [], "allowed_refs": [i["label"] for i in items], "corpus": "\n".join(texts),
             "evidence_count": len(items), "demo_input": {"product": profile, "competitor": {"name": "Momoyoga"}, "items": items}}
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_competitor_analysis(state)


@pytest.mark.asyncio
async def test_silence_about_our_features_is_not_an_opportunity():
    a = await analyse(HOMEPAGE)
    assert a["opportunities_for_us"] == []
    assert a["coverage"]["opportunities_for_us"] == "unknown"
    assert not any("does not mention" in f["statement"] for section in ("strengths", "positioning", "overlapping_features")
                   for f in a[section])


@pytest.mark.asyncio
async def test_opportunities_need_something_the_evidence_shows():
    a = await analyse(HOMEPAGE, "Offline mode is not available: the Momoyoga app requires an internet connection.")
    opps = a["opportunities_for_us"]
    assert len(opps) == 1 and opps[0]["refs"] == ["E2"] and opps[0]["status"] == "inferred"
    assert opps[0]["statement"].startswith("Suggestion:")  # a strategic suggestion, not a competitor fact
    assert "requires an internet connection" in opps[0]["statement"]


def test_grounding_moves_absence_claims_from_any_provider_to_evidence_gaps():
    output = {"opportunities_for_us": [
        {"statement": "Momoyoga does not mention automatic payment reminders, so we can own that.", "status": "inferred", "refs": ["E1"]},
        {"statement": "Their page states check-in requires an internet connection; highlight our offline mode.", "status": "inferred", "refs": ["E1"]},
    ]}
    result = ground_analysis(output, ["E1"], "check-in requires an internet connection", evidence_count=1)
    assert [f["statement"] for f in result["opportunities_for_us"]] == [
        "Their page states check-in requires an internet connection; highlight our offline mode."]
    assert result["opportunities_for_us"][0]["refs"] == ["E1"]  # citations kept
    assert EVIDENCE_GAP_PREFIX + "Momoyoga does not mention automatic payment reminders, so we can own that." in result["unknowns"]


@pytest.mark.asyncio
async def test_api_lists_each_unshown_feature_once_as_unknown_with_labelled_hypothesis(authenticated_client):
    _, product_id = await make_product(authenticated_client)
    competitor = await add_competitor(authenticated_client, product_id, name="Momoyoga")
    await add_note(authenticated_client, product_id, competitor["id"], text=HOMEPAGE)
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert res.status_code == 200, res.text
    analysis = res.json()["analysis"]

    assert analysis["opportunities_for_us"] == []
    unknowns = analysis["unknowns"]
    # LedgerLeaf (the test product): three features, none shown by the homepage → one unknown line each.
    feature_lines = [u for u in unknowns if u.startswith("Whether Momoyoga offers")]
    assert len(feature_lines) == 3 and len(set(feature_lines)) == 3
    for feature in ("GST invoice generation", "Expense categorisation"):
        assert sum(f'"{feature.lower()}"' in u.lower() for u in unknowns) == 1  # no duplicates
    # Differentiators the evidence doesn't mention are hypotheses to investigate, never confirmed weaknesses.
    hypotheses = [u for u in unknowns if "hypothesis" in u]
    assert hypotheses and all("not a confirmed weakness" in u for u in hypotheses)
    assert any("WhatsApp invoice sharing" in u for u in hypotheses)
    assert not any("weakness" in u and "not a confirmed" not in u for u in unknowns)
