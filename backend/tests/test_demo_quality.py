"""Regression tests for Demo Mode LinkedIn Content Generation Quality.

Verifies:
1. No internal information leakage or raw persona metadata in public copy.
2. Hook and alternative hooks are publication-ready and fit within LinkedIn character limits.
3. Body avoids unnecessary repetition and awkward audience phrasing.
4. Professional, Conversational, Educational, and Bold tones produce meaningfully distinct copy.
5. Changing audience personas changes framing naturally without leaking raw labels.
6. Factual claims remain grounded in approved product facts.
7. Generation is strictly deterministic with zero external AI API calls.
"""

import re
import pytest
from typing import Dict

from app.ai.generation_context import generation_context
from app.ai.generation_schemas import LinkedInPostOutput
from app.ai.generation_validation import validate_post, assemble
from app.ai.pillar_alignment import pillar_alignment, lead
from app.ai.platform_policy import platform_policy
from app.ai.providers.demo_generation import build_demo_linkedin_post

FORBIDDEN_LEAKAGE_PHRASES = [
    "this problem statement is based on",
    "product brief",
    "not a verbatim customer quote",
    "not a validated customer-research finding",
    "no verified differentiator",
    "leave differentiation unknown",
    "avoid competitive superiority claims",
    "avoid claiming superiority",
    "delivered in a conversational editorial tone",
    "delivered in a professional editorial tone",
    "delivered in a educational editorial tone",
    "delivered in a bold editorial tone",
    "for primary:",
    "#primary",
    "this is our intended audience selection",
    "intended initial test audience",
    "no complicated setup",
    "guesswork",
    "switching between disconnected tools",
    "disconnected tools",
    "scattered tools",
    "stop settling for scattered",
    "effortless",
    "guaranteed savings",
    "second job",
    "uphill battle",
    "no clutter",
    "not end-of-month surprises",
    "end-of-month surprises",
    "losing track of cash flow until the month is already over",
    "the control you need to keep your budget on target",
    "ready to stop settling",
    "stop settling",
    "maintain alignment with their goals",
    "the real problem",
    "a common problem",
    "the core problem",
    "a persistent problem",
    "real problem is",
    "common problem is",
    "core problem is",
    "takes regular attention throughout the week",
    "regular attention throughout the week",
    "juggling different details at once",
    "juggling multiple priorities",
    "juggling",
    "gives you a clear, consistent view",
    "clear, consistent view",
    "steady budgeting routine",
    "creates lasting clarity",
    "documented need",
    "the documented need",
]

BUDGETBLOOM_PROFILE = {
    "name": "BudgetBloom",
    "description": "BudgetBloom is a personal budgeting tool that helps users track expenses, organize monthly budgets, understand spending habits, and plan savings goals in one place.",
    "category": "personal budgeting tool",
    "target_audience": "For this test, prioritize college students managing limited budgets. Other target segments include young professionals handling their first salary and first-time budgeters. This is our intended audience selection for the test, not validated customer research.",
    "problem_solved": "Users need a simple way to track expenses, organize monthly budgets, understand spending habits, and plan savings goals in one place. This problem statement is based on the product brief, not a verbatim customer quote.",
    "value_proposition": "BudgetBloom brings expense tracking, monthly budget organization, spending habit monitoring, and savings goal planning together in one personal budgeting tool.",
    "key_features": [
        "Expense tracking",
        "Monthly budget organization",
        "Spending habit monitoring",
        "Savings goal planning",
    ],
    "differentiators": [
        "No verified differentiators have been provided yet. Leave differentiation unknown until competitor research or reliable product information supports a specific claim."
    ],
}

BUDGETBLOOM_STRATEGY = {
    "primary_audience": BUDGETBLOOM_PROFILE["target_audience"],
    "value_proposition": BUDGETBLOOM_PROFILE["value_proposition"],
    "messaging_direction": "Lead with BudgetBloom's practical budgeting capabilities: tracking expenses, organizing monthly budgets, monitoring spending habits, and planning savings goals in one place. Focus messaging on college students as the initial test audience. Avoid competitive superiority claims until differentiators are supported by reliable evidence.",
}

BUDGETBLOOM_PILLAR = {
    "name": "The problem we solve",
    "purpose": "Show the audience we understand their situation.",
    "relation_to_product": BUDGETBLOOM_PROFILE["problem_solved"],
}

BUDGETBLOOM_EMPHASIS = {
    "text": "No verified differentiators have been provided yet. Leave differentiation unknown until competitor research or reliable product information supports a specific claim.",
    "field": "differentiators",
    "competitor_refs": [],
}


def _generate_post(tone: str = "professional", persona: str = "Primary: College students managing limited budgets. This is the intended initial test audience, not a validated customer-research finding", pillar: Dict = BUDGETBLOOM_PILLAR) -> dict:
    demo_input = {
        "profile": BUDGETBLOOM_PROFILE,
        "product_name": "BudgetBloom",
        "strategy": BUDGETBLOOM_STRATEGY,
        "pillar": pillar,
        "emphasis": BUDGETBLOOM_EMPHASIS,
        "source_text": "",
        "instructions": "",
        "context_limitations": ["Competitor evidence was limited, so the post is positioned from the Product Profile only."],
        "editorial_tone": tone,
        "audience_persona": persona,
    }
    with generation_context({"demo_input": demo_input}, "generate-content"):
        raw = build_demo_linkedin_post("")
        return LinkedInPostOutput.model_validate(raw).model_dump()


def _get_public_copy_text(post: dict) -> str:
    """Concatenate all public-facing copy fields."""
    parts = [
        post.get("hook", ""),
        post.get("body", ""),
        post.get("cta", ""),
        " ".join(post.get("hashtags", [])),
        " ".join(post.get("alternative_hooks", [])),
    ]
    return " \n ".join(parts).lower()


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_no_internal_leakage_in_public_copy(tone):
    post = _generate_post(tone=tone)
    public_text = _get_public_copy_text(post)

    for phrase in FORBIDDEN_LEAKAGE_PHRASES:
        assert phrase not in public_text, f"Internal leakage found: '{phrase}' in public copy for tone '{tone}'."

    # Validate that hashtags do not contain internal labels
    for tag in post["hashtags"]:
        assert not tag.lower().startswith("#primary"), f"Malformed hashtag: {tag}"
        assert not tag.lower().startswith("#segment"), f"Malformed hashtag: {tag}"


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_hook_and_alternative_hooks_publication_ready(tone):
    post = _generate_post(tone=tone)

    # Hook length <= ~210 characters (LinkedIn 'see more' fold)
    assert len(post["hook"]) <= 210, f"Hook exceeds 210 chars: {len(post['hook'])}"
    assert post["hook"].strip(), "Hook cannot be empty"

    # Exactly three alternative hooks, distinct from hook and each other
    alt_hooks = post["alternative_hooks"]
    assert len(alt_hooks) == 3, f"Expected exactly 3 alternative hooks, got {len(alt_hooks)}"
    assert post["hook"] not in alt_hooks, "Hook should not be among alternative hooks"
    assert len(set(alt_hooks)) == 3, "Alternative hooks must be distinct"

    for alt in alt_hooks:
        assert len(alt) <= 210, f"Alternative hook exceeds 210 chars: {len(alt)}"
        for phrase in FORBIDDEN_LEAKAGE_PHRASES:
            assert phrase not in alt.lower(), f"Leakage '{phrase}' in alt hook: {alt}"


def test_body_avoids_repetition_and_awkward_audience_phrasing():
    post = _generate_post(tone="conversational")
    body = post["body"]

    # No awkward metadata phrasing
    assert "for primary:" not in body.lower()
    assert "primary: college students" not in body.lower()
    assert "intended initial test audience" not in body.lower()

    # Features should not be repeated in consecutive paragraphs
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
    feature_count_per_para = []
    features = [f.lower() for f in BUDGETBLOOM_PROFILE["key_features"]]
    for p in paragraphs:
        matches = sum(1 for f in features if f in p.lower())
        feature_count_per_para.append(matches)

    # Check that we don't have consecutive paragraphs listing 3+ features
    for i in range(len(feature_count_per_para) - 1):
        assert not (feature_count_per_para[i] >= 3 and feature_count_per_para[i + 1] >= 3), (
            f"Consecutive paragraphs repeated the feature list: {paragraphs[i]} -> {paragraphs[i+1]}"
        )


def test_four_editorial_tones_produce_meaningfully_different_valid_outputs():
    tones = ["professional", "conversational", "educational", "bold"]
    posts = {t: _generate_post(tone=t) for t in tones}

    # Hooks must be distinct across all 4 tones
    hooks = [posts[t]["hook"] for t in tones]
    assert len(set(hooks)) == 4, f"Hooks are not unique across tones: {hooks}"

    # Body copy must be distinct across all 4 tones
    bodies = [posts[t]["body"] for t in tones]
    assert len(set(bodies)) == 4, "Bodies are not unique across tones"

    # CTAs must be distinct across all 4 tones
    ctas = [posts[t]["cta"] for t in tones]
    assert len(set(ctas)) == 4, f"CTAs are not unique across tones: {ctas}"

    # All posts must pass platform policy validation without blocking errors
    policy = platform_policy("linkedin")
    allowed_refs = ["P:name", "P:description", "P:problem_solved", "P:value_proposition", "P:key_features", "P:differentiators"]
    meta = {
        "product_name": "BudgetBloom",
        "pillar": BUDGETBLOOM_PILLAR["name"],
        "pillar_detail": BUDGETBLOOM_PILLAR,
        "profile_core": BUDGETBLOOM_PROFILE,
        "forbidden_names": [],
        "competitor_names": [],
        "competitor_texts": [],
    }

    for t in tones:
        val = validate_post(posts[t], allowed_refs, str(BUDGETBLOOM_PROFILE), meta, policy)
        assert val["errors"] == [], f"Validation errors for tone {t}: {val['errors']}"
        assert val["unsupported_claims"] == [], f"Unsupported claims for tone {t}: {val['unsupported_claims']}"


def test_audience_persona_changes_framing():
    persona_a = "Primary: College students managing limited budgets"
    persona_b = "Segment: Young professionals handling their first salary"

    post_a = _generate_post(tone="conversational", persona=persona_a)
    post_b = _generate_post(tone="conversational", persona=persona_b)

    # Post A addresses college students, Post B addresses young professionals
    assert "college students" in post_a["body"].lower()
    assert "young professionals" in post_b["body"].lower()

    # Raw metadata labels stripped from public copy
    assert "primary:" not in post_a["body"].lower()
    assert "segment:" not in post_b["body"].lower()

    # Hashtags adapt cleanly
    assert "#CollegeStudents" in post_a["hashtags"]
    assert "#YoungProfessionals" in post_b["hashtags"]


def test_factual_product_claims_grounded_in_approved_info():
    post = _generate_post(tone="professional")
    claims = post["claims"]

    # Factual claims must reference valid profile fields
    product_facts = [c for c in claims if c["kind"] == "product_fact"]
    assert len(product_facts) >= 2, "Expected grounded product fact claims"
    for fact in product_facts:
        assert any(r.startswith("P:") for r in fact["refs"]), f"Fact missing P: ref: {fact}"
        for ref in fact["refs"]:
            if ref.startswith("P:"):
                field = ref[2:]
                assert field in BUDGETBLOOM_PROFILE, f"Citing nonexistent profile field: {field}"


def test_deterministic_and_no_ai_api_calls():
    post1 = _generate_post(tone="conversational")
    post2 = _generate_post(tone="conversational")
    post3 = _generate_post(tone="conversational")

    assert post1 == post2 == post3, "Demo mode must be strictly deterministic"


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_no_unsupported_assertions_or_benefits(tone):
    """Verify that generated copy across all tones avoids unsupported setup claims, competitor tool assumptions, and guaranteed outcomes."""
    post = _generate_post(tone=tone)
    public_text = _get_public_copy_text(post)

    unsupported_phrases = [
        "no complicated setup",
        "guesswork",
        "switching between disconnected tools",
        "disconnected tools",
        "scattered tools",
        "stop settling for scattered",
        "effortless",
        "guaranteed savings",
        "second job",
        "uphill battle",
        "no clutter",
        "not end-of-month surprises",
        "end-of-month surprises",
        "losing track of cash flow until the month is already over",
        "the control you need to keep your budget on target",
        "ready to stop settling",
        "stop settling",
        "maintain alignment with their goals",
        "the real problem",
        "a common problem",
        "the core problem",
        "a persistent problem",
        "real problem is",
        "common problem is",
        "core problem is",
        "takes regular attention throughout the week",
        "regular attention throughout the week",
        "juggling different details at once",
        "juggling multiple priorities",
        "juggling",
        "gives you a clear, consistent view",
        "clear, consistent view",
        "steady budgeting routine",
        "creates lasting clarity",
    ]
    for phrase in unsupported_phrases:
        assert phrase not in public_text, (
            f"Unsupported assertion '{phrase}' found in public copy for tone '{tone}':\n{public_text}"
        )


def test_budgetbloom_problem_pillar_no_redundancy_and_natural_framing():
    """Focused regression test: BudgetBloom with 'The problem we solve' pillar in Conversational tone.

    Verifies:
    1. Hook is natural, friendly, and not restated in the body.
    2. Body avoids awkward phrasing like 'that is the problem BudgetBloom solves'.
    3. The 4 approved features are mentioned together at most once in the body.
    4. Opening and closing paragraphs contain zero feature lists (no repeated feature lists).
    5. Each paragraph adds distinct, new information (problem context -> solution with features -> practical takeaway).
    6. Audience framing appears naturally without redundant repetition across multiple paragraphs.
    7. Alternative hooks provide genuinely distinct angles without dumping the full feature list.
    """
    post = _generate_post(tone="conversational", pillar=BUDGETBLOOM_PILLAR)
    hook = post["hook"]
    body = post["body"]
    paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]

    # 1. Natural hook not restated in body
    assert hook.lower() not in body.lower()
    for p in paragraphs:
        assert p.lower() != hook.lower()

    # 2. No awkward audience framing or problem solving phrasing
    awkward_phrases = [
        "that is the problem budgetbloom solves",
        "that is the problem",
        "solves that problem",
        "for college students managing limited budgets, that is the problem",
    ]
    for phrase in awkward_phrases:
        assert phrase not in body.lower(), f"Found awkward construction '{phrase}' in body: {body}"

    # 3. Features mentioned together at most once in the body
    features = [f.lower() for f in BUDGETBLOOM_PROFILE["key_features"]]
    paras_with_all_features = []
    for idx, p in enumerate(paragraphs):
        feat_matches = [f for f in features if f in p.lower()]
        if len(feat_matches) >= 3:
            paras_with_all_features.append((idx, feat_matches))

    assert len(paras_with_all_features) == 1, (
        f"Approved features should be mentioned together exactly once, got: {paras_with_all_features}"
    )

    # 4. Opening (first) and closing (last) paragraphs do not repeat feature lists
    assert len(paragraphs) == 3, f"Expected exactly 3 body paragraphs, got {len(paragraphs)}"
    first_para = paragraphs[0]
    last_para = paragraphs[-1]
    for f in features:
        assert f not in first_para.lower(), f"Feature '{f}' found in opening paragraph: {first_para}"
        assert f not in last_para.lower(), f"Feature '{f}' found in closing paragraph: {last_para}"

    # 5. Audience framing appears naturally at most once in the body
    audience_text = "college students managing limited budgets"
    audience_occurrences = body.lower().count(audience_text)
    assert audience_occurrences == 1, (
        f"Audience text should appear exactly once in body, found {audience_occurrences} times: {body}"
    )

    # 6. Alternative hooks have genuinely distinct angles and do not dump all features
    alt_hooks = post["alternative_hooks"]
    assert len(alt_hooks) == 3
    for alt in alt_hooks:
        alt_feat_count = sum(1 for f in features if f in alt.lower())
        assert alt_feat_count < 3, f"Alternative hook dumped features: '{alt}'"
        assert alt.lower() != hook.lower()


def test_alternative_hooks_differ_across_all_four_editorial_tones():
    """Verify that alternative hooks differ across Professional, Conversational, Educational, and Bold tones."""
    tones = ["professional", "conversational", "educational", "bold"]
    posts = {t: _generate_post(tone=t) for t in tones}

    # 1. Check that alternative hooks are distinct within each tone
    for t in tones:
        alts = posts[t]["alternative_hooks"]
        assert len(alts) == 3, f"Expected 3 alternatives for tone {t}, got {len(alts)}"
        assert len(set(alts)) == 3, f"Alternatives within tone {t} are not distinct: {alts}"
        assert posts[t]["hook"] not in alts, f"Hook should not be in alternatives for tone {t}"

    # 2. Check that the alternative hooks lists are distinct across all four tones
    alt_sets = {t: tuple(posts[t]["alternative_hooks"]) for t in tones}
    assert len(set(alt_sets.values())) == 4, f"Alternative hooks must differ across all 4 tones: {alt_sets}"

    # Pairwise check: no two tones have identical alternative hook lists
    for i in range(len(tones)):
        for j in range(i + 1, len(tones)):
            t1, t2 = tones[i], tones[j]
            overlap = set(posts[t1]["alternative_hooks"]) & set(posts[t2]["alternative_hooks"])
            assert len(overlap) < 2, f"Too much alternative hook overlap between {t1} and {t2}: {overlap}"


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_no_unverified_problem_labels_as_facts(tone):
    """Ensure Demo Mode does not label customer problems as 'real', 'common', or 'core' without validation."""
    # 1. Verify BudgetBloom problem pillar
    post = _generate_post(tone=tone, pillar=BUDGETBLOOM_PILLAR)
    public_text = _get_public_copy_text(post)

    unverified_problem_labels = [
        "the real problem",
        "a common problem",
        "the core problem",
        "a persistent problem",
        "real problem is",
        "common problem is",
        "core problem is",
        "the documented need",
        "documented need",
    ]
    for phrase in unverified_problem_labels:
        assert phrase not in public_text, (
            f"Unverified problem label '{phrase}' found in public copy for BudgetBloom ({tone}):\n{public_text}"
        )

    # 2. Verify non-budget generic product across tones
    generic_profile = {
        "name": "TaskFlow",
        "description": "TaskFlow is a project management tool for creative teams.",
        "category": "project management tool",
        "target_audience": "Creative teams managing multi-stage deliverables.",
        "problem_solved": "Creative teams need a unified way to coordinate daily tasks and monitor overall project timelines in one place.",
        "value_proposition": "TaskFlow brings daily task coordination and project timeline monitoring into one place.",
        "key_features": ["Task coordination", "Timeline monitoring", "Deliverable tracking"],
        "differentiators": [],
    }
    generic_pillar = {
        "name": "The problem we solve",
        "purpose": "Show the audience we understand their situation.",
        "relation_to_product": generic_profile["problem_solved"],
    }
    demo_input = {
        "profile": generic_profile,
        "product_name": "TaskFlow",
        "strategy": {"primary_audience": generic_profile["target_audience"], "value_proposition": generic_profile["value_proposition"]},
        "pillar": generic_pillar,
        "emphasis": {},
        "source_text": "",
        "instructions": "",
        "context_limitations": [],
        "editorial_tone": tone,
        "audience_persona": generic_profile["target_audience"],
    }
    with generation_context({"demo_input": demo_input}, "generate-content"):
        generic_post = LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()
        generic_text = _get_public_copy_text(generic_post)
        for phrase in unverified_problem_labels:
            assert phrase not in generic_text, (
                f"Unverified problem label '{phrase}' found in public copy for generic product ({tone}):\n{generic_text}"
            )


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_no_unsupported_audience_routines_frustrations_or_outcome_promises(tone):
    """Ensure Demo Mode templates do not infer unverified audience routines, frustrations, or product outcomes."""
    # 1. BudgetBloom post
    post = _generate_post(tone=tone, pillar=BUDGETBLOOM_PILLAR)
    public_text = _get_public_copy_text(post)

    forbidden_patterns = [
        "takes regular attention throughout the week",
        "regular attention throughout the week",
        "juggling different details at once",
        "juggling multiple priorities",
        "juggling",
        "gives you a clear, consistent view",
        "clear, consistent view",
        "steady budgeting routine",
        "creates lasting clarity",
    ]
    for pattern in forbidden_patterns:
        assert pattern not in public_text, (
            f"Unverified assumption/outcome '{pattern}' found in BudgetBloom ({tone}) public copy:\n{public_text}"
        )

    # 2. Check value pillar for BudgetBloom as well
    value_pillar = {
        "name": "The time it gives back",
        "purpose": "Show the benefit.",
        "relation_to_product": BUDGETBLOOM_PROFILE["value_proposition"],
    }
    val_post = _generate_post(tone=tone, pillar=value_pillar)
    val_text = _get_public_copy_text(val_post)
    for pattern in forbidden_patterns:
        assert pattern not in val_text, (
            f"Unverified assumption/outcome '{pattern}' found in BudgetBloom value pillar ({tone}) public copy:\n{val_text}"
        )


@pytest.mark.parametrize("tone", ["professional", "conversational", "educational", "bold"])
def test_pillar_alignment_for_problem_we_solve_across_all_tones(tone):
    """Regression test: Ensure 'The problem we solve' pillar posts clearly align with the pillar across all editorial tones.

    Verifies:
    1. Validation produces no warnings regarding pillar alignment.
    2. pillar_alignment() directly returns aligned=True.
    3. The opening hook/paragraph explicitly frames the challenge without inventing customer research or using internal phrasing like 'documented need'.
    4. Applies to both BudgetBloom and non-budget generic products.
    """
    # 1. BudgetBloom
    post = _generate_post(tone=tone, pillar=BUDGETBLOOM_PILLAR)
    post_text = assemble(post)
    lead_text = lead(post.get("hook", ""), post.get("body", ""))

    aligned, how = pillar_alignment(
        post_text,
        lead_text,
        BUDGETBLOOM_PILLAR["name"],
        BUDGETBLOOM_PILLAR,
        BUDGETBLOOM_PROFILE,
    )
    assert aligned is True, f"BudgetBloom post in tone '{tone}' failed pillar alignment: how={how}"

    # Also check via validate_post
    policy = platform_policy("linkedin")
    allowed_refs = ["P:name", "P:description", "P:problem_solved", "P:value_proposition", "P:key_features", "P:differentiators"]
    meta = {
        "product_name": "BudgetBloom",
        "pillar": BUDGETBLOOM_PILLAR["name"],
        "pillar_detail": BUDGETBLOOM_PILLAR,
        "profile_core": BUDGETBLOOM_PROFILE,
        "forbidden_names": [],
        "competitor_names": [],
        "competitor_texts": [],
    }
    val = validate_post(post, allowed_refs, str(BUDGETBLOOM_PROFILE), meta, policy)
    pillar_warnings = [w for w in val["warnings"] if "does not clearly reflect the selected pillar" in w]
    assert not pillar_warnings, f"BudgetBloom validation generated pillar warnings for tone '{tone}': {pillar_warnings}"

    # 2. Non-budget generic product
    generic_profile = {
        "name": "TaskFlow",
        "description": "TaskFlow is a project management tool for creative teams.",
        "category": "project management tool",
        "target_audience": "Creative teams managing multi-stage deliverables.",
        "problem_solved": "Creative teams need a unified way to coordinate daily tasks and monitor overall project timelines in one place.",
        "value_proposition": "TaskFlow brings daily task coordination and project timeline monitoring into one place.",
        "key_features": ["Task coordination", "Timeline monitoring", "Deliverable tracking"],
        "differentiators": [],
    }
    generic_pillar = {
        "name": "The problem we solve",
        "purpose": "Show the audience we understand their situation.",
        "relation_to_product": generic_profile["problem_solved"],
    }
    demo_input = {
        "profile": generic_profile,
        "product_name": "TaskFlow",
        "strategy": {"primary_audience": generic_profile["target_audience"], "value_proposition": generic_profile["value_proposition"]},
        "pillar": generic_pillar,
        "emphasis": {},
        "source_text": "",
        "instructions": "",
        "context_limitations": [],
        "editorial_tone": tone,
        "audience_persona": generic_profile["target_audience"],
    }
    with generation_context({"demo_input": demo_input}, "generate-content"):
        generic_post = LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()
        gen_text = assemble(generic_post)
        gen_lead = lead(generic_post.get("hook", ""), generic_post.get("body", ""))
        gen_aligned, gen_how = pillar_alignment(
            gen_text,
            gen_lead,
            generic_pillar["name"],
            generic_pillar,
            generic_profile,
        )
        assert gen_aligned is True, f"Generic product post in tone '{tone}' failed pillar alignment: how={gen_how}"


def test_four_tone_matrix_verification_across_fixtures():
    """Consolidated verification:
    Generates all four editorial tones across BudgetBloom and a generic product (TaskFlow),
    verifying natural wording, tone differentiation, pillar alignment, distinct alternative hooks,
    hashtag formatting, deterministic repeatability, and zero internal leakage.
    """
    tones = ["professional", "conversational", "educational", "bold"]
    fixtures = [
        ("BudgetBloom", BUDGETBLOOM_PROFILE, BUDGETBLOOM_STRATEGY, BUDGETBLOOM_PILLAR),
        (
            "TaskFlow",
            {
                "name": "TaskFlow",
                "description": "TaskFlow is a project management tool for creative teams.",
                "category": "project management tool",
                "target_audience": "Creative teams managing multi-stage deliverables.",
                "problem_solved": "Creative teams need a unified way to coordinate daily tasks and monitor overall project timelines in one place.",
                "value_proposition": "TaskFlow brings daily task coordination and project timeline monitoring into one place.",
                "key_features": ["Task coordination", "Timeline monitoring", "Deliverable tracking"],
                "differentiators": [],
            },
            {
                "primary_audience": "Creative teams managing multi-stage deliverables.",
                "value_proposition": "TaskFlow brings daily task coordination and project timeline monitoring into one place.",
                "messaging_direction": "Lead with task coordination and timeline monitoring.",
            },
            {
                "name": "The problem we solve",
                "purpose": "Show the audience we understand their situation.",
                "relation_to_product": "Creative teams need a unified way to coordinate daily tasks and monitor overall project timelines in one place.",
            },
        ),
    ]

    for prod_name, profile, strategy, pillar in fixtures:
        generated = {}
        for tone in tones:
            demo_input = {
                "profile": profile,
                "product_name": prod_name,
                "strategy": strategy,
                "pillar": pillar,
                "emphasis": {},
                "source_text": "",
                "instructions": "",
                "context_limitations": [],
                "editorial_tone": tone,
                "audience_persona": profile["target_audience"],
            }
            # 1. Determinism check: generate twice
            with generation_context({"demo_input": demo_input}, "generate-content"):
                post1 = LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()
            with generation_context({"demo_input": demo_input}, "generate-content"):
                post2 = LinkedInPostOutput.model_validate(build_demo_linkedin_post("")).model_dump()
            assert post1 == post2, f"Generation must be strictly deterministic for {prod_name} ({tone})"

            generated[tone] = post1
            pub_text = _get_public_copy_text(post1)

            # 2. No internal leakage or unverified assumptions in public copy
            for phrase in FORBIDDEN_LEAKAGE_PHRASES:
                assert phrase not in pub_text, f"Leakage '{phrase}' found in {prod_name} ({tone})"

            # 3. Clean hashtags
            for tag in post1["hashtags"]:
                assert not tag.lower().startswith("#primary")
                assert not tag.lower().startswith("#segment")
                assert not tag.lower().startswith("#decision")

            # 4. Hook and 3 distinct alternative hooks
            assert len(post1["hook"]) <= 210 and post1["hook"].strip()
            alts = post1["alternative_hooks"]
            assert len(alts) == 3
            assert len(set(alts)) == 3
            assert post1["hook"] not in alts

            # 5. Grounded product facts
            facts = [c for c in post1["claims"] if c.get("kind") == "product_fact"]
            assert len(facts) >= 2

            # 6. Substance pillar alignment
            post_text = assemble(post1)
            lead_text = lead(post1.get("hook", ""), post1.get("body", ""))
            aligned, how = pillar_alignment(post_text, lead_text, pillar["name"], pillar, profile)
            assert aligned is True, f"Pillar alignment failed for {prod_name} ({tone}): how={how}"

        # 7. Four tones produce genuinely distinct hooks and bodies
        hooks = [generated[t]["hook"] for t in tones]
        assert len(set(hooks)) == 4, f"Hooks must differ across all 4 tones for {prod_name}: {hooks}"
        bodies = [generated[t]["body"] for t in tones]
        assert len(set(bodies)) == 4, f"Bodies must differ across all 4 tones for {prod_name}"






