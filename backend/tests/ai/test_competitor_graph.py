"""Competitor Analysis: schemas, deterministic grounding, Demo Mode, and provider compatibility (mocked)."""
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.ai.competitor_grounding import ground_analysis, ground_comparison, has_unsupported_numbers
from app.ai.competitor_schemas import (
    FINDING_SECTIONS, PERFORMANCE_DATA_NOTE, ComparisonOutput, CompetitorAnalysisOutput, CompetitorSuggestionsOutput, Finding,
)
from app.ai.graphs.competitor_graph import run_competitor_analysis, run_competitor_comparison, run_competitor_suggestions
from app.ai.providers.claude_provider import ClaudeProvider

PRODUCT = {
    "name": "LedgerLeaf", "key_features": ["GST invoice generation", "Client payment tracker"],
    "differentiators": ["WhatsApp invoice sharing"],
}
EVIDENCE = (
    "Zoho Books is online accounting software for small businesses. "
    "Create GST invoices and track payments in one place. "
    "Read our blog for accounting tips. Follow us on LinkedIn. "
    "Join our free webinar every month."
)


def analysis_state(items):
    corpus = "\n".join(i["text"] for i in items) + str(PRODUCT)
    return {
        "prompt_context": [("Evidence", "x")],
        "allowed_refs": [i["label"] for i in items],
        "corpus": corpus,
        "evidence_count": sum(1 for i in items if i["label"].startswith("E")),
        "demo_input": {"product": PRODUCT, "competitor": {"name": "Zoho Books"}, "items": items},
    }


async def demo_analysis(items):
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_competitor_analysis(analysis_state(items))


# ─── Schemas ─────────────────────────────────────────────────────────────────

def test_schemas_default_to_empty_and_restrict_status():
    out = CompetitorAnalysisOutput()
    assert all(getattr(out, s) == [] for s in FINDING_SECTIONS)
    assert out.content_examples == []
    with pytest.raises(Exception):
        Finding(statement="x", status="certain", refs=[])
    assert ComparisonOutput().evidence_needed == []


def test_schemas_convert_to_claude_structured_output():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter
    for schema in (CompetitorAnalysisOutput, ComparisonOutput, CompetitorSuggestionsOutput):
        assert transform_schema(TypeAdapter(schema).json_schema())


# ─── Grounding ───────────────────────────────────────────────────────────────

def test_grounding_enforces_evidence_rules():
    raw = {
        "overview": [{"statement": "Accounting software for small businesses", "status": "observed", "refs": ["E1", "E9"]}],
        "positioning": [{"statement": "Positions itself as simple", "status": "observed", "refs": []}],
        "strengths": [{"statement": "Has 2 million customers", "status": "observed", "refs": ["E1"]}],
        "posting_cadence": [{"statement": "Probably posts often", "status": "inferred", "refs": ["E1"]}],
        "content_examples": [
            {"description": "Blog", "ref": "E1", "excerpt": "Read our blog for accounting tips"},
            {"description": "Invented", "ref": "E1", "excerpt": "Our viral TikTok series"},
        ],
    }
    out = ground_analysis(raw, ["E1"], EVIDENCE, evidence_count=1)
    assert out["overview"][0]["refs"] == ["E1"]                       # unknown ref E9 dropped
    assert out["positioning"][0]["status"] == "inferred"              # observed without refs is downgraded
    assert out["strengths"] == []                                     # invented number removed
    assert out["posting_cadence"] == []                               # cadence only when observed + cited
    assert [e["excerpt"] for e in out["content_examples"]] == ["Read our blog for accounting tips"]
    assert out["coverage"]["posting_cadence"] == "unknown"
    assert any("Posting cadence" in u for u in out["unknowns"])
    assert any("removed" in u for u in out["unknowns"])
    assert out["performance_data"] == PERFORMANCE_DATA_NOTE


def test_numbers_must_come_from_evidence():
    assert has_unsupported_numbers("posts 5 times a week", "we post daily") is True
    assert has_unsupported_numbers("Pro at Rs 299/month", "Pro at Rs 299/month") is False


def test_comparison_grounding_separates_and_cleans():
    raw = {
        "similarities": [{"statement": "Both offer GST invoices", "status": "observed", "refs": ["C1:E1", "C3:E1"]}],
        "positioning_opportunities": [
            {"suggestion": "Lead with WhatsApp sharing", "rationale": "Not mentioned by competitors", "refs": ["C1:E1"]},
            {"suggestion": "Beat their 40% growth", "rationale": "x", "refs": []},
        ],
    }
    out = ground_comparison(raw, ["C1:E1"], EVIDENCE)
    assert out["similarities"][0]["refs"] == ["C1:E1"]
    assert [s["suggestion"] for s in out["positioning_opportunities"]] == ["Lead with WhatsApp sharing"]
    assert any("performance" in e.lower() for e in out["evidence_needed"])


# ─── Demo Mode ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_without_evidence_produces_no_findings():
    out = await demo_analysis([])
    assert all(out[s] == [] for s in FINDING_SECTIONS)
    assert all(v == "unknown" for v in out["coverage"].values())


@pytest.mark.asyncio
async def test_demo_analysis_only_uses_supplied_evidence():
    out = await demo_analysis([{"label": "E1", "text": EVIDENCE}])
    text = str({s: out[s] for s in FINDING_SECTIONS})
    assert "Zoho Books" in text
    assert any("LinkedIn" in f["statement"] for f in out["promotion_channels"])
    assert any("Webinars" in f["statement"] for f in out["content_formats"])
    assert any("GST invoice generation" in f["statement"] for f in out["overlapping_features"])
    assert any("WhatsApp invoice sharing" in f["statement"] for f in out["opportunities_for_us"])
    # Monthly webinar is explicitly stated → observed cadence with a reference.
    assert out["posting_cadence"] and out["posting_cadence"][0]["refs"] == ["E1"]
    for section in FINDING_SECTIONS:
        for f in out[section]:
            assert set(f["refs"]) <= {"E1"}
            if f["status"] == "observed":
                assert f["refs"]
    # No numbers, companies, or channels that are not in the evidence.
    statements = " ".join(f["statement"] for sec in FINDING_SECTIONS for f in out[sec])
    assert set(re.findall(r"\d+", statements)) <= set(re.findall(r"\d+", EVIDENCE + str(PRODUCT)))
    for invented in ("Instagram", "TikTok", "QuickBooks", "Xero", "engagement rate"):
        assert invented not in text


@pytest.mark.asyncio
async def test_demo_cannot_suggest_competitors():
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        with pytest.raises(RuntimeError, match="Demo Mode cannot suggest competitors"):
            await run_competitor_suggestions({"prompt_context": []})


@pytest.mark.asyncio
async def test_demo_comparison_is_grounded():
    analysis = await demo_analysis([{"label": "E1", "text": EVIDENCE}])
    state = {
        "prompt_context": [], "allowed_refs": ["C1:E1"], "corpus": EVIDENCE + str(PRODUCT),
        "demo_input": {"product": PRODUCT, "competitors": [
            {"label": "C1", "name": "Zoho Books", "analysis": analysis, "items": [{"label": "E1", "text": EVIDENCE}]}]},
    }
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        out = await run_competitor_comparison(state)
    assert out["similarities"] and all(set(f["refs"]) <= {"C1:E1"} for f in out["similarities"])
    assert any("WhatsApp invoice sharing" in f["statement"] for f in out["differences"])
    assert any("LinkedIn" in s["suggestion"] for s in out["promotion_patterns_to_investigate"])


# ─── Real-provider compatibility (mocked Claude client) ──────────────────────

@pytest.mark.asyncio
async def test_claude_output_goes_through_the_same_grounding():
    model_output = CompetitorAnalysisOutput(
        overview=[Finding(statement="Online accounting for small businesses", status="observed", refs=["E1"])],
        strengths=[Finding(statement="Grew 300% last year", status="observed", refs=["E1"])],
        promotion_channels=[Finding(statement="Active on LinkedIn", status="observed", refs=["E7"])],
    )
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=model_output)

    provider = ClaudeProvider(api_key="test", client=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    with patch("app.ai.graphs.competitor_graph.get_provider", return_value=provider):
        out = await run_competitor_analysis(analysis_state([{"label": "E1", "text": EVIDENCE}]))

    assert calls[0]["output_format"] is CompetitorAnalysisOutput
    assert "DEMO MODE" not in calls[0]["messages"][0]["content"]
    assert out["overview"][0]["status"] == "observed"
    assert out["strengths"] == []                                   # invented 300% removed
    assert out["promotion_channels"][0]["status"] == "inferred"     # bad ref → not observed
    assert out["promotion_channels"][0]["refs"] == []
