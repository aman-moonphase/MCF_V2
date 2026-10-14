"""Demo Mode LinkedIn post for a product that is neither a budgeting app nor a task manager.

Profile = what the approved Plausible Analytics profile holds (facts from plausible.io/about and /data-policy).
Regression: the non-budget template used to invent "daily tasks / ongoing projects / workflows" copy that is not in the
approved profile (an analytics product was described as a task manager). Every sentence must now come from the profile.
"""
import re

import pytest

from app.ai.generation_context import generation_context
from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.generation_validation import assemble, validate_post
from app.ai.platform_policy import platform_policy
from app.ai.providers.demo_generation import build_demo_linkedin_post

PROFILE = {
    "name": "Plausible Analytics",
    "description": "Plausible Analytics is an independent, open source analytics company based in the EU.",
    "category": "Open source website analytics",
    "target_audience": "Website owners who want to understand their traffic without surveilling their visitors",
    "problem_solved": "Web analytics drifted from its purpose; site owners need a simple way to understand their traffic without surveilling their visitors.",
    "value_proposition": "A simple way for site owners to understand their traffic without surveilling their visitors.",
    "key_features": ["Visitor counting without cookies", "Open source code on GitHub", "Revenue measurement from conversions"],
    "differentiators": ["Open source and publicly verifiable"],
}
STRATEGY = {"primary_audience": PROFILE["target_audience"], "value_proposition": PROFILE["value_proposition"], "messaging_direction": "Lead with the value."}
PILLARS = {
    "problem": {"name": "The problem we solve", "purpose": "Show the audience we understand their situation.", "relation_to_product": PROFILE["problem_solved"]},
    "value": {"name": "The benefit it delivers", "purpose": f"Show the benefit: {PROFILE['value_proposition']}", "relation_to_product": PROFILE["value_proposition"]},
    "features": {"name": "How it works", "purpose": "Demonstrate concrete features.", "relation_to_product": "; ".join(PROFILE["key_features"])},
}
INVENTED = ["daily tasks", "ongoing projects", "daily execution", "workflow", "project plans", "central project", "core workflows"]


def post(tone, pillar="problem"):
    demo_input = {"profile": PROFILE, "product_name": PROFILE["name"], "strategy": STRATEGY, "pillar": PILLARS[pillar], "emphasis": {},
                  "source_text": "", "instructions": "", "context_limitations": [], "editorial_tone": tone, "audience_persona": "Website owners"}
    with generation_context({"demo_input": demo_input}, "generate-content"):
        return LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()


def public_text(p):
    return " ".join([p["hook"], p["body"], p["cta"], " ".join(p["hashtags"]), " ".join(p["alternative_hooks"])]).lower()


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
@pytest.mark.parametrize("pillar", ["problem", "value", "features"])
def test_no_invented_domain_copy_for_a_non_budget_product(tone, pillar):
    text = public_text(post(tone, pillar))
    for phrase in INVENTED:
        assert phrase not in text, f"{phrase!r} is not in the approved profile but appears in the {tone}/{pillar} post"
    assert "plausible analytics" in text


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_the_problem_post_is_built_from_the_approved_problem_and_value(tone):
    p = post(tone)
    text = " ".join([p["hook"], p["body"]]).lower()
    assert "surveilling their visitors" in text, "the approved problem/value reaches the post"
    assert len(p["hook"]) <= 210 and len(p["alternative_hooks"]) == 3
    assert all(len(h) <= 200 for h in p["alternative_hooks"])


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_the_post_passes_generation_validation_and_every_product_claim_cites_the_profile(tone):
    p = post(tone)
    allowed = ["P:problem_solved", "P:value_proposition", "P:key_features", "P:differentiators", "S1"]
    corpus = " ".join(str(v) for v in PROFILE.values()) + " " + " ".join(PROFILE["key_features"])
    report = validate_post(p, allowed, corpus, {"product_name": PROFILE["name"], "competitor_names": [], "forbidden_names": [],
                                                "pillar": PILLARS["problem"]["name"]}, platform_policy())
    assert report["errors"] == [], report["errors"]
    assert report["unsupported_claims"] == []
    assert all(any(r.startswith("P:") for r in c["refs"]) for c in p["claims"] if c["kind"] == "product_fact")


def test_the_four_tones_still_read_differently():
    hooks = {tone: post(tone)["hook"] for tone in ("professional", "conversational", "educational", "bold")}
    assert len(set(hooks.values())) == 4, hooks
    assert len({assemble(post(t)) for t in hooks}) == 4
