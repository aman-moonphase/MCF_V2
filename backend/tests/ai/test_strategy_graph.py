"""Promotion Strategy: schema, deterministic grounding, Demo Mode, and mocked real-provider compatibility."""
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.graphs.strategy_graph import run_promotion_strategy
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.strategy_grounding import ground_strategy
from app.ai.strategy_schemas import PromotionStrategyOutput

PROFILE = {
    "name": "LedgerLeaf", "target_audience": "solo designers and small studios",
    "problem_solved": "Designers lose hours reconciling GST by hand",
    "value_proposition": "Bookkeeping designers finish in minutes",
    "key_features": ["GST invoice generation", "Client payment tracker", "Expense categorisation", "UPI auto-import"],
    "differentiators": ["WhatsApp invoice sharing"],
}
ANALYSIS = {
    "promotion_channels": [{"statement": "The evidence references LinkedIn (presence only; activity level unknown)", "status": "observed", "refs": ["E1"]}],
    "references": {"E1": {"kind": "note", "evidence_id": "x", "title": "Notes", "url": None}},
}
COMPARISON = {
    "differences": [{"statement": "Our differentiator \"WhatsApp invoice sharing\" is not mentioned in any supplied competitor evidence.", "status": "inferred", "refs": []}],
    "positioning_opportunities": [{"suggestion": "Consider leading with \"WhatsApp invoice sharing\".", "rationale": "Not mentioned.", "refs": []}],
    "messaging_gaps": [], "similarities": [], "promotion_patterns_to_investigate": [], "evidence_needed": ["Zoho Books: no evidence about content formats."],
    "competitors": {"C1": {"competitor_id": "x", "name": "Zoho Books"}},
}


def state(limited=False, competitors=True):
    allowed = [f"profile:{k}" for k in PROFILE] + (["C1:E1"] if competitors else [])
    corpus = str(PROFILE) + (str(ANALYSIS) + str(COMPARISON) if competitors else "")
    return {
        "prompt_context": [("Profile", str(PROFILE))], "allowed_refs": allowed, "corpus": corpus, "meta": {"limited": limited},
        "demo_input": {"product": PROFILE, "comparison": None if limited else COMPARISON, "limited": limited,
                       "competitors": [{"label": "C1", "name": "Zoho Books", "analysis": ANALYSIS}] if competitors else []},
    }


async def demo(**kwargs):
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_promotion_strategy(state(**kwargs))


def groundings(s):
    yield s["executive_summary"]["grounding"]
    yield s["audience"]["grounding"]
    yield s["content_direction"]["grounding"]
    yield s["cadence"]["grounding"]
    for key in ("content_pillars", "channels", "roadmap", "measurement"):
        for item in s[key]:
            yield item["grounding"]


def minimal(**overrides):
    g = {"basis": "product_profile", "refs": [], "confidence": "medium"}
    base = {
        "executive_summary": {"positioning": "p", "main_opportunity": "o", "primary_recommendation": "r", "grounding": g},
        "audience": {"primary_audience": "a", "value_proposition": "v", "messaging_direction": "m", "grounding": g},
        "content_direction": {"primary_content_type": "Carousel", "reason": "r", "alternatives": ["Carousel", "Article", "Video", "Image"], "grounding": g},
        "cadence": {"frequency": "2 per week", "rationale": "r", "planning_horizon": "4 weeks", "is_hypothesis": False,
                    "grounding": {"basis": "product_profile", "refs": [], "confidence": "high"}},
    }
    base.update(overrides)
    return PromotionStrategyOutput.model_validate(base).model_dump()


# ─── Schema ──────────────────────────────────────────────────────────────────

def test_schema_rejects_unsupported_content_types_and_bases():
    with pytest.raises(Exception):
        minimal(content_direction={"primary_content_type": "Podcast", "reason": "r", "grounding": {"basis": "hypothesis"}})
    with pytest.raises(Exception):
        minimal(audience={"primary_audience": "a", "value_proposition": "v", "messaging_direction": "m", "grounding": {"basis": "a hunch"}})


def test_schema_converts_to_claude_structured_output():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter
    assert transform_schema(TypeAdapter(PromotionStrategyOutput).json_schema())


# ─── Grounding ───────────────────────────────────────────────────────────────

def test_grounding_rules():
    raw = minimal(
        executive_summary={"positioning": "Designer-first bookkeeping. Competitors grew 40% last year.", "main_opportunity": "o",
                           "primary_recommendation": "r", "grounding": {"basis": "competitor_observed", "refs": ["C9:E1"], "confidence": "high"}},
        measurement=[{"indicator": "Engagement", "what_to_measure": "Saves per post", "why": "Expect a 25% lift.",
                      "grounding": {"basis": "hypothesis", "refs": [], "confidence": "medium"}}],
        roadmap=[{"sequence": 2, "timing": "Week 2", "objective": "o", "topic": "t", "channel": "YouTube", "format": "Long-form video",
                  "audience": "a", "success_evaluation": "s", "grounding": {"basis": "hypothesis", "refs": []}},
                 {"sequence": 1, "timing": "Week 1", "objective": "o", "topic": "intro", "channel": "LinkedIn", "format": "Carousel",
                  "audience": "a", "success_evaluation": "s", "grounding": {"basis": "hypothesis", "refs": []}}],
    )
    out = ground_strategy(raw, ["C1:E1", "profile:name"], str(PROFILE), limited=False)
    es = out["executive_summary"]
    assert "40%" not in es["positioning"] and es["positioning"] == "Designer-first bookkeeping."
    assert es["grounding"]["basis"] == "hypothesis" and es["grounding"]["refs"] == []   # invalid competitor ref
    assert es["grounding"]["confidence"] == "medium"                                      # hypotheses are not "high"
    assert out["measurement"][0]["why"] == ""                                             # predicted result removed
    assert [r["topic"] for r in out["roadmap"]] == ["intro", "t"]                             # re-sequenced
    assert all(r["format"] == "Carousel" for r in out["roadmap"])                          # ONE content type
    assert out["content_direction"]["alternatives"] == ["Article", "Video"]
    assert out["cadence"]["is_hypothesis"] is True and out["cadence"]["grounding"]["basis"] == "hypothesis"
    assert any("figures" in l for l in out["limitations"])
    assert any("ONE" in l or "single MVP content type" in l for l in out["limitations"])


def test_limited_evidence_turns_competitor_claims_into_hypotheses():
    raw = minimal(audience={"primary_audience": "a", "value_proposition": "v", "messaging_direction": "m",
                            "grounding": {"basis": "competitor_observed", "refs": ["C1:E1"], "confidence": "high"}})
    out = ground_strategy(raw, ["C1:E1"], "", limited=True)
    assert out["audience"]["grounding"]["basis"] == "hypothesis"
    assert out["limitations"][0].startswith("Competitor Analysis was approved with limited evidence")


# ─── Demo Mode ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_strategy_uses_profile_and_competitor_intelligence():
    s = await demo()
    assert "LedgerLeaf" in s["executive_summary"]["positioning"]
    assert s["content_direction"]["primary_content_type"] == "Carousel"
    assert s["content_direction"]["primary_content_type"] not in s["content_direction"]["alternatives"]
    linkedin = next(c for c in s["channels"] if c["channel"] == "LinkedIn")
    assert linkedin["grounding"]["basis"] == "competitor_observed" and linkedin["grounding"]["refs"] == ["C1:E1"]
    assert "presence only" in linkedin["rationale"]
    assert s["executive_summary"]["grounding"]["basis"] == "evidence_inferred"
    assert any(p["grounding"]["basis"] == "product_profile" for p in s["content_pillars"])
    assert any(g["basis"] == "hypothesis" for g in groundings(s))
    assert all(r["format"] == "Carousel" for r in s["roadmap"]) and len(s["roadmap"]) >= 3
    assert any("Zoho Books: no evidence" in l for l in s["limitations"])


@pytest.mark.asyncio
async def test_demo_strategy_does_not_fabricate():
    s = await demo()
    text = str({k: v for k, v in s.items() if k not in ("cadence", "roadmap")})
    allowed_numbers = set(re.findall(r"\d+", str(PROFILE) + str(ANALYSIS) + str(COMPARISON)))
    assert set(re.findall(r"\d+", re.sub(r"[CE]\d+", "", text))) <= allowed_numbers
    for invented in ("QuickBooks", "Xero", "Instagram reach", "%", "conversion rate of", "followers"):
        assert invented not in text
    assert s["cadence"]["is_hypothesis"] is True


@pytest.mark.asyncio
async def test_demo_strategy_with_limited_evidence_is_honest():
    s = await demo(limited=True, competitors=False)
    assert all(g["basis"] not in ("competitor_observed", "evidence_inferred") for g in groundings(s))
    assert s["limitations"][0].startswith("Competitor Analysis was approved with limited evidence")
    assert "Zoho" not in str(s)


# ─── Mocked real provider ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_claude_strategy_goes_through_the_same_schema_and_grounding():
    model_output = PromotionStrategyOutput.model_validate(minimal(
        channels=[{"channel": "LinkedIn", "priority": "primary", "rationale": "Competitors are present there.",
                   "formats": ["Carousel"], "grounding": {"basis": "competitor_observed", "refs": ["C1:E1"], "confidence": "high"}},
                  {"channel": "TikTok", "priority": "secondary", "rationale": "Competitors win there with 2M views.",
                   "formats": [], "grounding": {"basis": "competitor_observed", "refs": [], "confidence": "high"}}],
    ))
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=model_output)

    provider = ClaudeProvider(api_key="test", client=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    with patch("app.ai.graphs.competitor_graph.get_provider", return_value=provider):
        s = await run_promotion_strategy(state())
    assert calls[0]["output_format"] is PromotionStrategyOutput
    assert "DEMO MODE" not in calls[0]["messages"][0]["content"]
    assert s["channels"][0]["grounding"]["basis"] == "competitor_observed"
    tiktok = s["channels"][1]
    assert tiktok["grounding"]["basis"] == "hypothesis" and "2M" not in tiktok["rationale"]
