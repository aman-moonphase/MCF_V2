"""Regression (manual StudioDesk test): with the pillar "The problem we solve" the Demo Mode post mostly listed
features and the pillar-alignment check warned. Each pillar must now change the hook and body, using only the
approved profile/strategy, and genuinely pass the (unchanged) alignment check.
"""
import re

import pytest

from app.ai.generation_context import generation_context
from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.generation_validation import assemble, validate_post
from app.ai.platform_policy import platform_policy
from app.ai.providers.demo_generation import build_demo_linkedin_post, pillar_kind

DIFFERENTIATOR = "Offline attendance check-in helps teachers manage attendance even without an internet connection"
PROFILE = {
    "name": "StudioDesk",
    "description": "StudioDesk is a booking and invoicing app for independent yoga teachers.",
    "category": "booking and invoicing app",
    "target_audience": "Independent yoga teachers who teach in rented studios.",
    "problem_solved": ("StudioDesk helps independent yoga teachers manage class bookings, invoicing, payment reminders, and "
                       "attendance, so they spend less time on administrative work and chasing payments."),
    "value_proposition": "Spend time teaching, not chasing payments.",
    "key_features": ["Class booking links", "Automatic payment reminders", "Attendance tracking", "Offline attendance check-in"],
    "differentiators": [DIFFERENTIATOR],
}
STRATEGY = {"primary_audience": PROFILE["target_audience"], "value_proposition": PROFILE["value_proposition"],
            "messaging_direction": "Lead with \"Spend time teaching, not chasing payments\". Differentiate with: " + DIFFERENTIATOR}
PILLARS = {
    "problem": {"name": "The problem we solve", "purpose": "Show the audience we understand their situation.",
                "relation_to_product": PROFILE["problem_solved"]},
    "value": {"name": "The time it gives back", "purpose": "Show the benefit: Spend time teaching, not chasing payments.",
              "relation_to_product": "The approved value proposition: Spend time teaching, not chasing payments."},
    "features": {"name": "How it works", "purpose": "Demonstrate concrete features.",
                 "relation_to_product": "Class booking links; Automatic payment reminders; Attendance tracking; Offline attendance check-in"},
    "differentiator": {"name": "Offline attendance check-in", "purpose": "Own a differentiator of StudioDesk.",
                       "relation_to_product": DIFFERENTIATOR + ". Listed as a differentiator in the profile."},
}
SOURCE = ("Product: StudioDesk. Description: StudioDesk is a booking and invoicing app for independent yoga teachers. "
          "Features: Class booking links, Automatic payment reminders, Attendance tracking, Offline attendance check-in. "
          "Value proposition: Spend time teaching, not chasing payments. Differentiator: " + DIFFERENTIATOR + ".")
REFS = ["S1"] + [f"P:{k}" for k in PROFILE]
CORPUS = SOURCE + str(PROFILE) + str(STRATEGY)


def generate(kind: str) -> dict:
    demo_input = {"profile": PROFILE, "product_name": "StudioDesk", "strategy": STRATEGY, "pillar": PILLARS[kind],
                  "emphasis": {"text": DIFFERENTIATOR, "field": "differentiators", "competitor_refs": []},
                  "source_text": SOURCE, "instructions": "", "context_limitations": []}
    with generation_context({"demo_input": demo_input}, "generate-content"):
        return LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()


def validate(post: dict, pillar: str) -> dict:
    meta = {"product_name": "StudioDesk", "pillar": pillar, "forbidden_names": ["LedgerLeaf"],
            "competitor_names": ["Momoyoga"], "competitor_texts": []}
    return validate_post(post, REFS, CORPUS, meta, platform_policy())


def test_pillars_are_classified_from_the_approved_strategy():
    assert {k: pillar_kind(p, PROFILE) for k, p in PILLARS.items()} == {k: k for k in PILLARS}


def test_problem_pillar_leads_with_the_burden_then_the_solution():
    post = generate("problem")
    assert post["hook"] == "How much of your week goes to administrative work and chasing payments?"
    first = post["body"].split("\n\n")[0]
    assert first.startswith("For independent yoga teachers who teach in rented studios, that is the problem StudioDesk solves.")
    assert PROFILE["problem_solved"] in first
    assert "What it does:" not in post["body"]  # not a feature list
    assert post["body"].index("problem StudioDesk solves") < post["body"].index("class booking links")


def test_time_pillar_leads_with_the_value_proposition():
    post = generate("value")
    assert post["hook"] == "Spend time teaching, not chasing payments."
    assert post["body"].startswith("That is what StudioDesk is for.")
    assert "so less of your week goes to administrative work and chasing payments" in post["body"]


def test_how_it_works_pillar_explains_every_feature():
    post = generate("features")
    assert post["hook"] == "Here is how StudioDesk works for independent yoga teachers who teach in rented studios."
    assert "What it does:\n" + "\n".join(f"→ {f}" for f in PROFILE["key_features"]) in post["body"]


def test_differentiator_pillar_leads_with_offline_check_in():
    post = generate("differentiator")
    assert post["hook"] == DIFFERENTIATOR + "."
    assert "It is one of the things that makes StudioDesk different." in post["body"]
    assert "Offline attendance check-in" not in post["body"].split("Alongside it:")[-1]  # not repeated as "another" feature


def test_each_pillar_changes_hook_and_body():
    posts = {k: generate(k) for k in PILLARS}
    assert len({p["hook"] for p in posts.values()}) == 4
    assert len({p["body"] for p in posts.values()}) == 4
    for kind, post in posts.items():
        assert post["pillar"] == PILLARS[kind]["name"]
        assert len(post["alternative_hooks"]) == 3 and post["hook"] not in post["alternative_hooks"]


@pytest.mark.parametrize("kind", list(PILLARS))
def test_posts_are_grounded_readable_and_aligned(kind):
    post = generate(kind)
    report = validate(post, PILLARS[kind]["name"])
    text = assemble(report["post"])
    assert report["errors"] == []
    assert report["warnings"] == []  # incl. the pillar-alignment check: met by the content, not suppressed
    assert report["unsupported_claims"] == []
    facts = [c for c in report["post"]["claims"] if c["kind"] == "product_fact"]
    assert facts and all(any(r.startswith(("P:", "S")) for r in c["refs"]) for c in facts)
    # No invented figures, testimonials, outcomes or competitor claims.
    assert not re.search(r"\d", text)
    assert not re.search(r"\b(customers? (?:say|love)|testimonial|saved \w+ hours|increase[sd]?|momoyoga|competitor)\b", text, re.I)
    # Punctuation: no doubled stops, no dangling colons, every paragraph ends properly.
    assert ".." not in text and ":." not in text and ": ." not in text
    for paragraph in report["post"]["body"].split("\n\n"):
        assert paragraph.rstrip()[-1] in ".?!" or paragraph.startswith("What it does:"), paragraph


def test_alignment_check_still_warns_on_a_mismatched_post():
    features_post = generate("features")
    report = validate(features_post, "The problem we solve")
    assert any("does not clearly reflect the selected pillar 'The problem we solve'" in w for w in report["warnings"])
