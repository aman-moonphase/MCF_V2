"""LinkedIn post generation: schema + platform validation, the deterministic demo builder, MVP type steering,
and the shared schema through mocked Claude and OpenAI providers (no network, no API key)."""
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.generation_context import generation_context
from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.generation_validation import assemble, validate_post
from app.ai.graphs.generation_graph import run_linkedin_generation
from app.ai.platform_policy import (GENERATION_SUPPORTED_TYPES, apply_mvp_content_type, generation_support,
                                    platform_policy)
from app.ai.providers.claude_provider import ClaudeProvider
from app.ai.providers.demo_generation import DEMO_LIMITATION, build_demo_linkedin_post
from app.ai.providers.demo_provider import DemoProvider
from app.core.config import settings

POST = {
    "hook": "Bookkeeping designers finish in minutes.",
    "alternative_hooks": ["Invoices on WhatsApp.", "Built for solo designers.", "Tax reminders on time."],
    "body": "LedgerLeaf creates GST invoices and shares them on WhatsApp.",
    "cta": "Try LedgerLeaf for your studio.",
    "hashtags": ["#LedgerLeaf"],
    "claims": [{"text": "LedgerLeaf creates GST invoices", "kind": "product_fact", "refs": ["P:key_features"]}],
    "pillar": "How it works", "strategy_alignment": "Follows the messaging direction.", "limitations": [],
}
REFS = ["S1", "P:key_features", "P:differentiators", "C1:E1"]
CORPUS = "LedgerLeaf: GST invoice generation, WhatsApp invoice sharing, quarterly tax reminders."
META = {"product_name": "LedgerLeaf", "pillar": "How it works", "forbidden_names": ["Bloomly"],
        "competitor_names": ["Zoho Books"], "competitor_texts": ["Zoho Books is online accounting software for small businesses everywhere."]}

PROFILE = {
    "name": "LedgerLeaf", "description": "A bookkeeping app for freelance designers in India",
    "category": "bookkeeping software", "target_audience": "freelance designers",
    "problem_solved": "Designers lose evenings to invoices and GST paperwork",
    "value_proposition": "Bookkeeping designers finish in minutes",
    "key_features": ["GST invoice generation", "expense categorisation", "quarterly tax reminders"],
    "differentiators": ["WhatsApp invoice sharing"],
}
STRATEGY = {"primary_audience": "freelance designers", "value_proposition": "Bookkeeping designers finish in minutes",
            "messaging_direction": "Lead with WhatsApp invoice sharing"}


def check(post, **meta):
    return validate_post(post, REFS, CORPUS, {**META, **meta}, platform_policy())


def codes(report):
    return {i["code"] for i in report["issues"]}


# ─── Validation ─────────────────────────────────────────────────────────────

def test_valid_post_passes():
    report = check(POST)
    assert report["errors"] == [] and report["within_limit"] is True
    assert report["character_count"] == len(assemble(report["post"]))


@pytest.mark.parametrize("change, code", [
    ({"hook": ""}, "missing"),
    ({"alternative_hooks": ["Invoices on WhatsApp.", "invoices on whatsapp", POST["hook"]]}, "alternatives"),
    ({"body": "LedgerLeaf. " + "x" * 3000}, "over_limit"),
    ({"cta": "Visit [insert link] to try LedgerLeaf"}, "placeholder"),
    ({"body": 'LedgerLeaf {"hook": "x"}'}, "json"),
    ({"body": "LedgerLeaf cuts bookkeeping time by 73%."}, "unsupported_number"),
    ({"body": "LedgerLeaf and Bloomly together."}, "cross_product"),
    ({"body": "LedgerLeaf beats Zoho Books."}, "competitor_named"),
    ({"body": "LedgerLeaf is online accounting software for small businesses everywhere."}, "competitor_copy"),
    ({"body": "Bookkeeping in minutes.", "hook": "Invoices made easy.", "cta": "Try it.", "hashtags": []}, "product_missing"),
])
def test_hard_errors(change, code):
    assert code in codes(check({**POST, **change}))


def test_soft_findings_are_warnings():
    report = check({**POST, "hook": "LedgerLeaf " * 30, "hashtags": ["a", "#b", "c d", "e", "f", "g", "#a"],
                    "claims": [{"text": "Works offline", "kind": "product_fact", "refs": ["X9", "C1:E1"]}]},
                   pillar="Answering competitor messages")
    assert report["errors"] == []
    assert report["post"]["hashtags"] == ["#a", "#b", "#cd", "#e", "#f"]
    assert report["post"]["claims"][0]["refs"] == ["C1:E1"]  # unknown refs dropped
    assert report["unsupported_claims"] == ["Works offline"]
    assert len(report["warnings"]) == 4  # hashtags, hook length, pillar, unsupported claim


def test_character_limit_is_configurable(monkeypatch):
    monkeypatch.setattr(settings, "LINKEDIN_POST_MAX_CHARS", 100)
    assert "over_limit" in codes(check(POST)) and platform_policy().max_chars == 100


def test_only_social_post_is_generatable():
    assert GENERATION_SUPPORTED_TYPES == {"Social Post"} and generation_support("Social Post") is None
    for other in ("Video", "Image", "Carousel", "Article", "Newsletter"):
        assert other in generation_support(other)


# ─── MVP strategy steering ──────────────────────────────────────────────────

def test_strategy_is_steered_to_social_post_without_losing_the_original():
    g = {"basis": "hypothesis", "refs": [], "confidence": "low"}
    strategy = {
        "content_direction": {"primary_content_type": "Carousel", "reason": "Many features.", "alternatives": ["Article", "Social Post"]},
        "channels": [{"channel": "Instagram", "priority": "primary", "formats": ["Carousel"], "rationale": "r", "grounding": g},
                     {"channel": "LinkedIn", "priority": "secondary", "formats": ["Carousel"], "rationale": "r", "grounding": g}],
        "roadmap": [{"format": "Carousel"}], "cadence": {"frequency": "1-2 carousels per week"}, "limitations": [],
    }
    s = apply_mvp_content_type(strategy)
    cd = s["content_direction"]
    assert cd["primary_content_type"] == "Social Post" and cd["alternatives"] == ["Carousel", "Article"]
    assert "Carousel" in s["limitations"][-1] and s["roadmap"][0]["format"] == "Social Post"
    assert [(c["channel"], c["priority"]) for c in s["channels"]] == [("LinkedIn", "primary"), ("Instagram", "secondary")]
    assert s["cadence"]["frequency"] == "2-3 posts per week"
    assert apply_mvp_content_type(s)["limitations"] == s["limitations"]  # idempotent


# ─── Demo builder ───────────────────────────────────────────────────────────

def demo_post(**overrides):
    demo_input = {"profile": PROFILE, "product_name": "LedgerLeaf", "strategy": STRATEGY,
                  "pillar": {"name": "How it works"}, "emphasis": {"text": "WhatsApp invoice sharing", "field": "differentiators",
                                                                   "competitor_refs": ["C1:E1"]},
                  "source_text": "features: gst invoice generation, whatsapp invoice sharing", "instructions": "",
                  "context_limitations": [], **overrides}
    with generation_context({"demo_input": demo_input}, "generate-content"):
        return LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()


def test_demo_post_uses_the_product_and_cites_it():
    post = demo_post()  # pillar "How it works": the features
    text = assemble(post)
    assert "LedgerLeaf" in text and "GST invoice generation" in text
    assert "freelance designers" in text
    assert len(set(post["alternative_hooks"])) == 3 and post["hook"] not in post["alternative_hooks"]
    assert post["limitations"][0] == DEMO_LIMITATION
    gst = next(c for c in post["claims"] if c["text"] == "GST invoice generation")
    assert gst["refs"] == ["P:key_features", "S1"]
    assert check(post, pillar="How it works")["errors"] == []

    # The differentiator (and the competitor evidence that informed choosing it) leads its own pillar's post.
    diff = demo_post(pillar={"name": "WhatsApp invoice sharing",
                             "relation_to_product": "WhatsApp invoice sharing. Listed as a differentiator in the profile."})
    assert "WhatsApp invoice sharing" in diff["hook"] and "LedgerLeaf" in assemble(diff)
    assert any(c["kind"] == "competitor_context" and c["refs"] == ["C1:E1"] for c in diff["claims"])
    assert check(diff, pillar="WhatsApp invoice sharing")["errors"] == []


def test_demo_never_fabricates():
    sparse = {"name": "Tiny", "description": "A note-taking app"}
    post = demo_post(profile=sparse, product_name="Tiny", strategy={}, emphasis={}, source_text="", instructions="Mention our 50% sale")
    text = assemble(post)
    assert not re.search(r"\d", text)  # no invented numbers, and the instruction's figure is not used
    assert any("cannot interpret your campaign instructions" in x for x in post["limitations"])
    assert any("no value proposition" in x for x in post["limitations"]) and any("no features" in x for x in post["limitations"])
    assert "LedgerLeaf" not in text and "What it does" not in text


def test_demo_changes_with_the_pillar_and_audience():
    a = demo_post()
    b = demo_post(pillar={"name": "The problem we solve"}, strategy={**STRATEGY, "primary_audience": "wedding photographers"})
    assert a["hook"] != b["hook"] and b["hook"].startswith("Designers lose evenings")
    assert "wedding photographers" in assemble(b) and b["pillar"] == "The problem we solve"


# ─── The graph with each provider (shared schema) ───────────────────────────

STATE = {"prompt_context": [("Profile", "LedgerLeaf")], "allowed_refs": REFS, "corpus": CORPUS, "meta": META}


@pytest.mark.asyncio
async def test_graph_with_demo_provider():
    state = {**STATE, "demo_input": {"profile": PROFILE, "product_name": "LedgerLeaf", "strategy": STRATEGY,
                                     "pillar": {"name": "How it works"}, "emphasis": {}, "source_text": ""}}
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=DemoProvider()):
        result = await run_linkedin_generation(state)
    assert "LedgerLeaf" in assemble(result["post"]) and result["validation"]["errors"] == []
    assert "\n" in result["post"]["body"] and "\\" not in result["post"]["body"]  # real line breaks, no escapes


@pytest.mark.asyncio
async def test_graph_with_mocked_claude():
    calls = []

    async def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(stop_reason="end_turn", parsed_output=LinkedInPostOutput.model_validate(POST))

    provider = ClaudeProvider(api_key="test-key", model_name="claude-opus-5-5", max_tokens=1000, effort="medium",
                              client=SimpleNamespace(messages=SimpleNamespace(parse=parse)))
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        result = await run_linkedin_generation(STATE)
    assert calls[0]["output_format"] is LinkedInPostOutput
    assert "Write ONE LinkedIn post" in calls[0]["messages"][0]["content"]
    assert result["post"]["hook"] == POST["hook"]


@pytest.mark.asyncio
async def test_graph_with_mocked_openai_retries_invalid_output():
    from app.ai.providers.openai_provider import OpenAIProvider

    provider = OpenAIProvider(api_key="sk-test")
    bad = LinkedInPostOutput.model_validate({**POST, "body": "LedgerLeaf is used by 10,000 designers."})
    structured = MagicMock()
    structured.ainvoke = AsyncMock(side_effect=[bad, LinkedInPostOutput.model_validate(POST)])
    provider.llm = MagicMock()
    provider.llm.with_structured_output = MagicMock(return_value=structured)
    with patch("app.ai.graphs.generation_graph.get_provider", return_value=provider):
        result = await run_linkedin_generation(STATE)
    provider.llm.with_structured_output.assert_called_with(LinkedInPostOutput)
    assert structured.ainvoke.await_count == 2
    retry_prompt = structured.ainvoke.call_args_list[1].args[0][1].content
    assert "PREVIOUS ATTEMPT WAS REJECTED" in retry_prompt and "figure" in retry_prompt
    assert result["post"]["body"] == POST["body"]
