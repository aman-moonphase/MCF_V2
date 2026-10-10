"""Regression (manual StudioDesk / Momoyoga test), comparison stage:
1. a competitor's generic CTA ("Get started for free") was reported as a confirmed messaging gap only because
   our profile does not contain the same phrase;
2. "More evidence needed" did not list the feature comparisons the supplied evidence leaves unresolved.
"""
import re

import pytest

from app.ai.competitor_grounding import CTA_SUGGESTION_PREFIX, ground_comparison
from tests.test_competitor_analysis import add_competitor, add_note, make_product

# The test product is LedgerLeaf: features "GST invoice generation", "Expense categorisation", "A client payment tracker".
EVIDENCE = ("Momoyoga is booking software built for yoga studios. Create GST invoices and track payments in one place. "
            "Get started for free.")
ABSENCE_WORDS = re.compile(r"\b(?:lacks?|does not offer|doesn't offer|no support for|absent|missing)\b", re.I)


async def analyse_and_compare(client, text=EVIDENCE):
    _, product_id = await make_product(client)
    competitor = await add_competitor(client, product_id, name="Momoyoga")
    await add_note(client, product_id, competitor["id"], text=text)
    analysed = await client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert analysed.status_code == 200, analysed.text
    compared = await client.post(f"/api/products/{product_id}/competitor-comparison")
    assert compared.status_code == 200, compared.text
    return analysed.json()["analysis"], compared.json()["comparison"]


# ─── 1. Generic CTA ─────────────────────────────────────────────────────────

def test_generic_cta_is_a_labelled_suggestion_not_a_messaging_gap():
    raw = {"messaging_gaps": [
        {"statement": 'Momoyoga uses a message our profile does not address — Message used: "Get started for free"',
         "status": "observed", "refs": ["C1:E1"]},
        {"statement": "Momoyoga stresses community events for students, which our profile does not cover",
         "status": "observed", "refs": ["C1:E1"]},
    ]}
    out = ground_comparison(raw, ["C1:E1"], "Get started for free. community events for students")
    gaps = [f["statement"] for f in out["messaging_gaps"]]
    assert gaps == ["Momoyoga stresses community events for students, which our profile does not cover"]
    assert out["messaging_gaps"][0]["status"] == "observed" and out["messaging_gaps"][0]["refs"] == ["C1:E1"]
    cta = [s for s in out["promotion_patterns_to_investigate"] if s["suggestion"].startswith(CTA_SUGGESTION_PREFIX)]
    assert len(cta) == 1 and '"Get started for free"' in cta[0]["suggestion"] and cta[0]["refs"] == ["C1:E1"]
    assert "not a messaging gap" in cta[0]["rationale"]


@pytest.mark.asyncio
async def test_cta_stays_an_observed_competitor_message_end_to_end(authenticated_client):
    # "Request a demo" shares no words with the LedgerLeaf profile, so the demo comparison would otherwise call it a gap.
    analysis, comparison = await analyse_and_compare(authenticated_client, text="Momoyoga studio scheduling. Request a demo today.")
    observed = [f for f in analysis["messaging_themes"] if "Request a demo today" in f["statement"]]
    assert observed and observed[0]["status"] == "observed" and observed[0]["refs"] == ["E1"]
    assert not any("request a demo" in f["statement"].lower() for f in comparison["messaging_gaps"])
    cta = [s for s in comparison["promotion_patterns_to_investigate"] if "Request a demo today" in s["suggestion"]]
    assert len(cta) == 1 and cta[0]["suggestion"].startswith(CTA_SUGGESTION_PREFIX) and cta[0]["refs"] == ["C1:E1"]


# ─── 2. Unresolved feature comparisons ──────────────────────────────────────

@pytest.mark.asyncio
async def test_unresolved_feature_comparisons_are_listed_as_evidence_needed(authenticated_client):
    analysis, comparison = await analyse_and_compare(authenticated_client)
    needed = comparison["evidence_needed"]
    unresolved = [e for e in needed if "does not establish whether Momoyoga offers" in e]
    # Only "Expense categorisation" is not touched by the evidence; the other two have (partial) cited matches.
    assert len(unresolved) == 1 and '"Expense categorisation"' in unresolved[0]
    assert "unresolved (not evidence that the feature is absent)" in unresolved[0]
    assert needed.index(unresolved[0]) == 0  # listed before the generic notes
    covered = {f["statement"].split('"')[1] for f in analysis["overlapping_features"]}
    assert covered == {"GST invoice generation", "A client payment tracker"}
    assert all(f["status"] == "inferred" and f["refs"] == ["C1:E1"] for f in comparison["similarities"])


@pytest.mark.asyncio
async def test_no_feature_evidence_means_every_comparison_is_unresolved_never_absent(authenticated_client):
    _, comparison = await analyse_and_compare(authenticated_client, text="Momoyoga is booking software built for yoga studios. Get started for free.")
    unresolved = [e for e in comparison["evidence_needed"] if "does not establish whether Momoyoga offers" in e]
    assert len(unresolved) == 3 and len(set(unresolved)) == 3
    everything = " ".join([*comparison["evidence_needed"], *[f["statement"] for k in ("similarities", "differences", "messaging_gaps")
                                                              for f in comparison[k]]])
    assert not ABSENCE_WORDS.search(everything.replace("not evidence that the feature is absent", ""))
    assert comparison["similarities"] == []  # nothing invented
    for f in comparison["differences"]:
        assert f["status"] == "inferred" and "not mentioned in any supplied competitor evidence" in f["statement"]
