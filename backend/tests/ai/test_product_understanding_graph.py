"""Product Understanding: schema, LangGraph workflow, Demo Mode, gaps, questions, provider compatibility."""
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.graphs.product_understanding_graph import run_product_understanding
from app.ai.nodes.product_understanding_nodes import (
    clean_profile, identify_gaps, merge_profiles, validate_understanding,
)
from app.ai.product_schemas import (
    CRITICAL_FIELDS, LIST_FIELDS, MAX_QUESTIONS, PROFILE_FIELDS, ClarificationQuestionsOutput,
    ProductProfile, ProductProfileDraft,
)
from app.ai.providers.claude_provider import ClaudeProvider

LEDGERLEAF = (
    "Product: LedgerLeaf - a bookkeeping app for freelance designers in India. "
    "Features: auto-import of UPI and bank transactions, GST invoice generation, expense categorisation, "
    "quarterly advance-tax reminders, and a client payment tracker. "
    "Pricing: free tier up to 20 invoices/month, Pro at Rs 299/month. "
    "Target users: solo designers and small studios who hate spreadsheets. "
    "Main alternatives people use today: Zoho Books, Vyapar, Excel sheets. "
    "Differentiator: built for creative freelancers, setup in 5 minutes, WhatsApp invoice sharing."
)
SPARSE = "A bookkeeping platform for freelance designers that turns client invoices into tax-ready records."
FORBIDDEN = ["ai coding", "coding assistant", "developer", "software engineer", "boilerplate", "javascript", "typist"]


async def demo(source, **kwargs):
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return await run_product_understanding(source, **kwargs)


# ─── 1. Schema ───────────────────────────────────────────────────────────────

def test_profile_schema_fields_and_defaults():
    expected = {
        "name", "description", "category", "problem_solved", "target_audience", "primary_users", "key_features",
        "key_benefits", "differentiators", "use_cases", "value_proposition", "positioning", "market_geography",
        "business_model", "known_competitors", "website_url", "constraints",
    }
    assert set(PROFILE_FIELDS) == expected
    assert {"key_features", "known_competitors", "differentiators"} <= LIST_FIELDS
    profile = ProductProfile()
    assert profile.key_features == [] and profile.name is None and profile.confidence == "low"
    assert profile.missing_fields == [] and profile.source_references == []


def test_placeholders_are_normalised_to_missing():
    cleaned = clean_profile({"name": "Unknown", "category": " n/a ", "key_features": ["", "unknown", "Invoices"]})
    assert cleaned["name"] is None and cleaned["category"] is None
    assert cleaned["key_features"] == ["Invoices"]


def test_merge_preserves_existing_and_edited_fields():
    current = {"name": "LedgerLeaf", "category": "bookkeeping", "value_proposition": "Edited by user"}
    new = {"name": None, "category": "accounting", "value_proposition": "Model rewrite"}
    merged = merge_profiles(new, current, edited_fields=["value_proposition"])
    assert merged["name"] == "LedgerLeaf"          # never blanked by a refresh
    assert merged["category"] == "accounting"      # refreshed from sources
    assert merged["value_proposition"] == "Edited by user"  # user edits win


# ─── 2-3. Graph + Demo Mode ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_profile_describes_the_actual_product():
    result = await demo(LEDGERLEAF)
    p = result["profile"]
    assert p["name"] == "LedgerLeaf"
    assert "bookkeeping" in p["category"]
    assert "GST invoice generation" in p["key_features"]
    assert "solo designers" in p["target_audience"]
    assert p["known_competitors"] == ["Zoho Books", "Vyapar", "Excel sheets"]
    assert "Rs 299/month" in p["business_model"]
    assert p["market_geography"] == "India"
    assert "WhatsApp invoice sharing" in p["differentiators"]


@pytest.mark.asyncio
async def test_demo_profile_contains_no_unrelated_fixture_content():
    for source in (LEDGERLEAF, SPARSE):
        text = str((await demo(source))["profile"]).lower()
        assert not any(word in text for word in FORBIDDEN)


# ─── 13. No fabrication ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_demo_does_not_fabricate_missing_information():
    p = (await demo(SPARSE))["profile"]
    for field in ("name", "business_model", "market_geography", "website_url", "value_proposition", "positioning"):
        assert p[field] is None, field
    assert p["known_competitors"] == []
    # Every number in the profile must come from the source.
    source_numbers = set(re.findall(r"\d+", LEDGERLEAF))
    full = await demo(LEDGERLEAF)
    assert set(re.findall(r"\d+", str(full["profile"]))) <= source_numbers


# ─── 4-5. Missing information + clarification questions ──────────────────────

def test_identify_gaps_prioritises_critical_fields():
    state = {"profile": {"name": "X", "key_features": ["a"]}, "asked_fields": []}
    gaps = identify_gaps(state)
    assert "target_audience" in gaps["missing_fields"]
    assert gaps["askable_fields"][0] == "target_audience"
    assert "name" not in gaps["askable_fields"]


def test_no_questions_when_only_non_critical_fields_are_missing():
    profile = {f: "x" for f in CRITICAL_FIELDS}
    profile["key_features"] = ["x"]
    gaps = identify_gaps({"profile": profile, "asked_fields": []})
    assert gaps["askable_fields"] == []
    assert "website_url" in gaps["missing_fields"]


def test_already_asked_fields_are_not_asked_again():
    gaps = identify_gaps({"profile": {"name": "X"}, "asked_fields": ["target_audience", "problem_solved"]})
    assert "target_audience" not in gaps["askable_fields"]
    assert "problem_solved" not in gaps["askable_fields"]


@pytest.mark.asyncio
async def test_demo_asks_only_about_missing_critical_information():
    full = await demo(LEDGERLEAF)
    asked = {f for q in full["questions"] for f in q["fields"]}
    assert asked <= {"problem_solved", "value_proposition"}  # everything else is in the source
    assert not any("colour" in q["question"].lower() or "color" in q["question"].lower() for q in full["questions"])

    sparse = await demo(SPARSE)
    assert 1 <= len(sparse["questions"]) <= MAX_QUESTIONS
    for q in sparse["questions"]:
        assert q["question"] and q["why_it_matters"] and q["fields"]
        assert all(f in sparse["missing_fields"] for f in q["fields"])


def test_validation_filters_bad_questions():
    state = {
        "profile": {"name": "X"},
        "askable_fields": ["target_audience", "problem_solved"],
        "questions": [
            {"question": "Who buys it?", "why_it_matters": "Targeting", "fields": ["target_audience"]},
            {"question": "Who buys it??", "why_it_matters": "Duplicate", "fields": ["target_audience"]},
            {"question": "What colour is the brand?", "why_it_matters": "Looks", "fields": ["brand_colour"]},
            {"question": "What is the name?", "why_it_matters": "Already known", "fields": ["name"]},
            {"question": "No reason", "why_it_matters": "", "fields": ["problem_solved"]},
        ] + [{"question": f"Q{i}", "why_it_matters": "w", "fields": ["problem_solved"]} for i in range(10)],
    }
    kept = validate_understanding(state)["questions"]
    assert kept[0]["question"] == "Who buys it?"
    assert len(kept) == MAX_QUESTIONS
    assert all(set(q["fields"]) <= {"target_audience", "problem_solved"} for q in kept)
    assert sum(1 for q in kept if q["question"].startswith("Who buys")) == 1


@pytest.mark.asyncio
async def test_answers_update_the_profile_in_demo_mode():
    first = await demo(SPARSE)
    result = await demo(
        SPARSE,
        current_profile=first["profile"],
        clarifications=[{"question": "Name?", "fields": ["name"], "answer": "InvoiceNest"},
                        {"question": "Features?", "fields": ["key_features"], "answer": "invoice capture, GST export"}],
        asked_fields=[f for q in first["questions"] for f in q["fields"]],
    )
    assert result["profile"]["name"] == "InvoiceNest"
    assert result["profile"]["key_features"] == ["Invoice capture", "GST export"]
    assert result["profile"]["category"] == first["profile"]["category"]  # preserved
    assert result["questions"] == []  # nothing is re-asked


@pytest.mark.asyncio
async def test_graph_fails_cleanly_without_sources():
    with pytest.raises(RuntimeError, match="No product sources"):
        await demo("   ")


# ─── 14. Real provider compatibility (mocked) ────────────────────────────────

@pytest.mark.asyncio
async def test_same_schema_works_with_claude_provider_mock():
    draft = ProductProfileDraft(name="LedgerLeaf", category="bookkeeping software", key_features=["GST invoices"])
    questions = ClarificationQuestionsOutput(questions=[
        {"question": "Who is the primary customer: freelance designers, agencies, or both?",
         "why_it_matters": "Targeting", "fields": ["target_audience"]},
    ])

    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        out = draft if kwargs["output_format"] is ProductProfileDraft else questions
        return SimpleNamespace(stop_reason="end_turn", parsed_output=out)

    async def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text="analysis")])

    provider = ClaudeProvider(api_key="test", client=SimpleNamespace(messages=SimpleNamespace(parse=parse, create=create)))
    with patch("app.ai.nodes.product_understanding_nodes.get_provider", return_value=provider):
        result = await run_product_understanding(LEDGERLEAF)

    assert result["profile"]["name"] == "LedgerLeaf"
    assert result["questions"][0]["fields"] == ["target_audience"]
    assert {c.get("output_format") for c in calls if "output_format" in c} == {ProductProfileDraft, ClarificationQuestionsOutput}
    for c in calls:
        assert "DEMO MODE" not in c["messages"][0]["content"]
        assert LEDGERLEAF in c["messages"][0]["content"]


def test_schemas_convert_to_claude_structured_output():
    from anthropic.lib._parse._transform import transform_schema
    from pydantic import TypeAdapter
    for schema in (ProductProfileDraft, ClarificationQuestionsOutput):
        assert transform_schema(TypeAdapter(schema).json_schema())


@pytest.mark.asyncio
async def test_provider_failures_are_retried_then_reported():
    provider = MagicMock()
    provider.generate_text = AsyncMock(return_value="analysis")
    provider.generate_structured = AsyncMock(side_effect=RuntimeError("boom"))
    with patch("app.ai.nodes.product_understanding_nodes.get_provider", return_value=provider):
        with pytest.raises(RuntimeError, match="Failed to build product profile"):
            await run_product_understanding(LEDGERLEAF)
    assert provider.generate_structured.call_count == 3
