"""Demo Mode competitor analysis on SCRAPED web-page text (navigation, buttons, pricing copy).

The excerpt is public text from usefathom.com. Regression for three real defects: page chrome ("Skip to main content",
"View a live demo", "Help centre") was reported as positioning/messaging, and a pricing sentence ("Sites on a plan share
your monthly pageviews") was reported as the competitor's posting cadence. Real cadence statements must still count.
"""
import pytest

from app.core.config import settings
from tests.test_promotion_strategy import make_product

PAGE = (
    "Skip to main content. Fathom Analytics: Privacy-First Google Analytics Alternative. "
    "Fathom is a Google Analytics alternative that makes your analytics easy to understand and respects visitor privacy. "
    "Sites on a plan share your monthly pageviews. View a live demo. Help centre. Read article. "
    "Subscribe to our email newsletter for product updates."
)
PUBLISHING = "Fathom publishes a new blog post every week and sends a newsletter monthly."


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def analysis_for(client, text):
    project_id, product_id = await make_product(client)
    competitor = (await client.post(f"/api/products/{product_id}/competitors", json={"name": "Fathom Analytics"})).json()
    res = await client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/evidence", data={"evidence_type": "note", "content": text})
    assert res.status_code == 201, res.text
    done = await client.post(f"/api/products/{product_id}/competitors/{competitor['id']}/analyze")
    assert done.status_code == 200, done.text
    return done.json()["analysis"]


def statements(analysis, section):
    return [f["statement"] for f in analysis.get(section) or []]


@pytest.mark.asyncio
async def test_page_chrome_is_not_positioning_or_messaging(authenticated_client):
    analysis = await analysis_for(authenticated_client, PAGE)
    spoken = " | ".join(statements(analysis, "positioning") + statements(analysis, "messaging_themes"))
    for chrome in ("Skip to main content", "View a live demo", "Help centre", "Read article"):
        assert chrome not in spoken, f"{chrome!r} reported as the competitor's own message"
    assert any("Google Analytics alternative" in s for s in statements(analysis, "positioning")), "the real positioning sentence is kept"


@pytest.mark.asyncio
async def test_a_pricing_sentence_is_not_a_posting_cadence(authenticated_client):
    analysis = await analysis_for(authenticated_client, PAGE)
    assert analysis["posting_cadence"] == [], statements(analysis, "posting_cadence")


@pytest.mark.asyncio
async def test_a_stated_publishing_frequency_is_still_reported(authenticated_client):
    analysis = await analysis_for(authenticated_client, PAGE + " " + PUBLISHING)
    cadence = statements(analysis, "posting_cadence")
    assert any("every week" in s for s in cadence) and not any("pageviews" in s for s in cadence), cadence
