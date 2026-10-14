"""Demo Mode product understanding on REAL marketing/policy prose (not a structured brief).

The excerpts are public text from plausible.io/about and plausible.io/data-policy. Regression for three real defects:
a sentence about data collection became "key features", an anaphoric sentence ("This allows...") became the value
proposition, and a sentence about revenue became a differentiator. Unstated facts must stay unknown.
"""
import pytest

from app.core.config import settings

ABOUT = (
    "About | Plausible Analytics Plausible Analytics is an independent, open source analytics company based in the EU. "
    "We built it because web analytics had drifted far from its purpose: a simple way for site owners to understand their "
    "traffic without surveilling their visitors. We do not use cookies and we do not collect personal data. "
    "How we are funded: We are self-funded and profitable, with no outside investors and no plans to sell. "
    "Subscription revenue is the only revenue we have. It funds our team, infrastructure and product development."
)
POLICY = (
    "Plausible: GDPR, CCPA and cookie law compliant web analytics | Plausible Analytics. "
    "We do not generate persistent identifiers. We do not use cookies, browser cache or local storage. "
    "Every HTTP request includes IP address and User-Agent. We use these to generate a daily identifier. "
    "Why should I trust you? Plausible is an open source website analytics tool. Our source code is publicly available "
    "on GitHub. This allows independent verification of our claims."
)


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")


async def profile_from(client, *texts):
    created = await client.post("/api/projects", json={"title": "Real prose", "source_type": "Text Idea", "source_reference": "x"})
    project_id = created.json()["id"]
    for text in texts:
        res = await client.post(f"/api/projects/{project_id}/sources/ingest", data={"source_type": "text", "content": text})
        assert res.status_code == 200, res.text
    res = await client.post(f"/api/projects/{project_id}/product-understanding")
    assert res.status_code == 200, res.text
    return res.json()["profile"]


@pytest.mark.asyncio
async def test_data_collection_sentences_are_not_product_features(authenticated_client):
    profile = await profile_from(authenticated_client, ABOUT, POLICY)
    features = " ".join(profile.get("key_features") or [])
    assert "IP address" not in features and "User-Agent" not in features, features


@pytest.mark.asyncio
async def test_an_anaphoric_sentence_is_not_the_value_proposition(authenticated_client):
    profile = await profile_from(authenticated_client, ABOUT, POLICY)
    assert not (profile.get("value_proposition") or "").lower().startswith("this "), profile.get("value_proposition")


@pytest.mark.asyncio
async def test_funding_statements_are_a_business_model_not_a_differentiator(authenticated_client):
    profile = await profile_from(authenticated_client, ABOUT, POLICY)
    assert not any("revenue" in d.lower() for d in profile.get("differentiators") or []), profile.get("differentiators")
    assert "subscription" in (profile.get("business_model") or "").lower()


@pytest.mark.asyncio
async def test_facts_the_sources_do_not_state_stay_unknown(authenticated_client):
    profile = await profile_from(authenticated_client, ABOUT, POLICY)
    assert profile["name"] == "Plausible Analytics"
    for field in ("target_audience", "primary_users", "key_benefits", "use_cases", "known_competitors"):
        assert not profile.get(field), f"{field} was invented: {profile.get(field)}"
        assert field in profile["missing_fields"]
    assert "problem_solved" in profile["missing_fields"] or "site owners" in (profile.get("problem_solved") or "").lower()
