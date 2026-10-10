"""Regression (manual StudioDesk / Momoyoga test):
1. a shared word ("attendance") in pricing / promo-code marketing was reported as a competitor having our
   "Attendance tracking" feature;
2. web pages served without a charset were stored as mojibake ("Iâ\\x80\\x99m"), which then appeared in quotes.
"""
from unittest.mock import patch
from uuid import UUID

import pytest
import requests
from sqlalchemy import update

from app.ai.graphs.competitor_graph import run_competitor_analysis
from app.core.config import settings
from app.core.text_encoding import has_mojibake, repair_mojibake
from app.models.competitor import CompetitorEvidence
from app.services.extraction_service import ExtractionService

FEATURES = ["Class booking links", "Automatic payment reminders", "Attendance tracking", "Offline attendance check-in"]
PROFILE = {"name": "StudioDesk", "key_features": FEATURES,
           "differentiators": ["Offline attendance check-in helps teachers manage attendance even without an internet connection"]}
PROMO = "Encourage sign-ups with tiered pricing, exclusive event rates and promo codes that help you maximise attendance."
TESTIMONIAL = "“A trusted and quality partner I’m proud to support as a studio founder — café naïve.”"
MOJIBAKE_TESTIMONIAL = TESTIMONIAL.encode("utf-8").decode("latin-1")  # what was stored before the fix


async def analyse(*texts, profile=PROFILE):
    items = [{"label": f"E{i}", "text": t} for i, t in enumerate(texts, start=1)]
    state = {"prompt_context": [], "allowed_refs": [i["label"] for i in items], "corpus": "\n".join(texts),
             "evidence_count": len(items), "demo_input": {"product": profile, "competitor": {"name": "Momoyoga"}, "items": items}}
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_competitor_analysis(state)


def overlaps(analysis):
    return {f["statement"].split('"')[1]: f for f in analysis["overlapping_features"]}


# ─── 1. Feature matching ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_promo_code_marketing_is_not_attendance_tracking():
    a = await analyse(PROMO, "Discover your strengths, from yogi attendance to individual teacher performance.")
    assert "Attendance tracking" not in overlaps(a)
    assert "Offline attendance check-in" not in overlaps(a)
    assert a["overlapping_features"] == []


@pytest.mark.asyncio
async def test_real_booking_and_payment_evidence_still_matches():
    a = await analyse(
        "Students book classes through your class booking links on any device.",
        "Momoyoga sends automatic payment reminders to students with open invoices.",
        "Teachers use attendance tracking to see who came to each class.",
    )
    found = overlaps(a)
    assert found["Class booking links"]["status"] == "observed" and found["Class booking links"]["refs"] == ["E1"]
    assert found["Automatic payment reminders"]["status"] == "observed" and found["Automatic payment reminders"]["refs"] == ["E2"]
    assert found["Attendance tracking"]["status"] == "observed" and found["Attendance tracking"]["refs"] == ["E3"]
    assert "Offline attendance check-in" not in found  # nothing says check-in works offline


@pytest.mark.asyncio
async def test_partial_overlap_is_inferred_not_observed():
    a = await analyse("All-in-one yoga studio management software for class scheduling, bookings, payments, and online teaching.")
    found = overlaps(a)
    assert found["Class booking links"]["status"] == "inferred"
    assert "partial match" in found["Class booking links"]["statement"]
    assert "Attendance tracking" not in found and "Automatic payment reminders" not in found


@pytest.mark.asyncio
async def test_words_far_apart_or_in_quotes_do_not_match():
    a = await analyse(
        "Attendance at our annual retreat was wonderful and every teacher kept tracking their own goals.",
        "“Attendance tracking changed my studio”, says one teacher.",
    )
    assert a["overlapping_features"] == []


@pytest.mark.asyncio
async def test_unsupported_features_are_reported_as_unknown(authenticated_client):
    from tests.test_competitor_analysis import add_competitor, add_note, make_product
    _, product_id = await make_product(authenticated_client)
    competitor = await add_competitor(authenticated_client, product_id, name="Momoyoga")
    await add_note(authenticated_client, product_id, competitor["id"], text=PROMO + " Get started for free.")
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert res.status_code == 200, res.text
    analysis = res.json()["analysis"]
    assert analysis["overlapping_features"] == []
    unknown = [u for u in analysis["unknowns"] if u.startswith("Whether Momoyoga offers")]
    # LedgerLeaf's three features: none is supported by a promo-code sentence, so each stays unknown.
    assert len(unknown) == 3
    assert any('"GST invoice generation"' in u for u in unknown) and any('client payment tracker"' in u.lower() for u in unknown)


# ─── 2. Encoding ────────────────────────────────────────────────────────────

def test_repair_restores_mojibake_and_leaves_valid_unicode_alone():
    assert repair_mojibake(MOJIBAKE_TESTIMONIAL) == TESTIMONIAL
    assert repair_mojibake("Iâ€™m") == "I’m"  # the cp1252 form of the same damage
    for valid in (TESTIMONIAL, "Café © 2024", "Ã la carte", "日本語 \U0001F600", "plain text"):
        assert repair_mojibake(valid) == valid
        assert not has_mojibake(valid)
    assert has_mojibake(MOJIBAKE_TESTIMONIAL)


def _page(body: str, content_type: str) -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = f"<html><head><title>Momoyoga</title></head><body><p>{body}</p></body></html>".encode("utf-8")
    response.headers["Content-Type"] = content_type
    response.url = "https://www.momoyoga.com/"
    return response


@pytest.mark.parametrize("content_type", ["text/html", "text/html; charset=utf-8"])
def test_url_extraction_decodes_utf8_pages(content_type):
    with patch("app.core.url_safety.safe_get", return_value=_page(TESTIMONIAL, content_type)):
        result = ExtractionService.extract_from_url("https://www.momoyoga.com/")
    assert TESTIMONIAL in result.text and not has_mojibake(result.text)


@pytest.mark.asyncio
async def test_quotes_survive_analysis_unchanged():
    a = await analyse("The only yoga dedicated platform out there.", TESTIMONIAL)
    text = str(a)
    assert "I’m proud" in text and "— café naïve" in text and not has_mojibake(text)


@pytest.mark.asyncio
async def test_unrecoverable_text_is_never_quoted():
    broken = "The only platform � for studios."
    a = await analyse(broken, "The only yoga dedicated platform out there.")
    assert "�" not in str(a)


@pytest.mark.asyncio
async def test_stored_mojibake_evidence_is_repaired_when_analysed(authenticated_client, db_session):
    from tests.test_competitor_analysis import add_competitor, add_note, make_product
    _, product_id = await make_product(authenticated_client)
    competitor = await add_competitor(authenticated_client, product_id, name="Momoyoga")
    evidence = await add_note(authenticated_client, product_id, competitor["id"], text="placeholder")
    # Simulate a page stored before the fix (UTF-8 decoded as Latin-1).
    await db_session.execute(update(CompetitorEvidence).where(CompetitorEvidence.id == UUID(evidence["id"]))
                             .values(content="The only yoga dedicated platform out there. " + MOJIBAKE_TESTIMONIAL))
    await db_session.commit()
    res = await authenticated_client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert res.status_code == 200, res.text
    analysis = str(res.json()["analysis"])
    assert "I’m proud" in analysis and "â\x80" not in analysis and not has_mojibake(analysis)


@pytest.mark.asyncio
async def test_unicode_survives_text_ingestion(authenticated_client, db_session):
    from tests.test_competitor_analysis import add_competitor, add_note, make_product
    _, product_id = await make_product(authenticated_client)
    competitor = await add_competitor(authenticated_client, product_id, name="Momoyoga")
    stored = await add_note(authenticated_client, product_id, competitor["id"], text=TESTIMONIAL)
    row = await db_session.get(CompetitorEvidence, UUID(stored["id"]))
    assert row.content == TESTIMONIAL
