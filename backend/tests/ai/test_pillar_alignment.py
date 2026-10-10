"""Pillar alignment (generation-time warning).

Regression (TaskNest real-AI draft): a post that states the approved problem in its own words — "how much of your
week goes to managing work instead of designing", juggling projects, tasks and deadlines — was warned as "does not
clearly reflect the selected pillar 'The problem we solve'", because only the pillar NAME's words were matched.
Grounded paraphrases of each pillar's substance now pass; genuinely mismatched posts still warn.
"""
import pytest

from app.ai.generation_validation import assemble, validate_post
from app.ai.pillar_alignment import lead, pillar_alignment, pillar_context, pillar_kind
from app.ai.platform_policy import platform_policy

PROFILE = {
    "name": "TaskNest",
    "target_audience": "Freelance designers",
    "problem_solved": "TaskNest helps freelance designers organize projects, track tasks, and stay on top of deadlines so "
                      "they spend less time managing work and more time delivering projects.",
    "value_proposition": "Spend less time organizing work and more time delivering projects",
    "key_features": ["Task boards", "Deadline reminders", "Project tracking"],
    "differentiators": ["Simple project tracking designed for independent freelancers"],
}
PILLARS = {
    "problem": {"name": "The problem we solve", "purpose": "Show the audience we understand their situation.",
                "relation_to_product": PROFILE["problem_solved"]},
    "value": {"name": "The time it gives back", "purpose": "Show the benefit: " + PROFILE["value_proposition"],
              "relation_to_product": "The approved value proposition: " + PROFILE["value_proposition"]},
    "features": {"name": "How it works", "purpose": "Demonstrate concrete features.",
                 "relation_to_product": "Task boards; Deadline reminders; Project tracking"},
    "differentiator": {"name": "Project tracking", "purpose": "Own a differentiator of TaskNest.",
                       "relation_to_product": "Simple project tracking designed for independent freelancers. "
                                              "Listed as a differentiator in the profile."},
}

# The saved TaskNest draft (Claude, version 1), verbatim.
TASKNEST_DRAFT = {
    "hook": "Freelance designers: how much of your week goes to managing work instead of designing?",
    "body": ("When you're an independent designer, there's no one else to keep the work in order. You're juggling projects, "
             "tracking tasks, and watching deadlines, all on top of the creative work clients actually hired you for.\n"
             "That's the situation TaskNest is built for. It's a task-management app for freelance designers that helps you "
             "organize projects, track tasks, and stay on top of deadlines.\n"
             "Here's what that looks like in practice:\n"
             "• Task boards to organize your work\n"
             "• Deadline reminders so due dates don't slip by\n"
             "• Project tracking that's simple and designed for independent freelancers\n"
             "The goal is straightforward: spend less time managing work and more time delivering projects."),
    "cta": "If you're a freelance designer, what's the most time-consuming part of keeping your projects organized? "
           "Tell us in the comments.",
    "hashtags": ["#FreelanceDesign", "#FreelanceDesigners", "#TaskManagement", "#ProjectTracking", "#TaskNest"],
}


def aligned(post: dict, kind: str):
    pillar = PILLARS[kind]
    return pillar_alignment(assemble(post), lead(post["hook"], post["body"]), pillar["name"], pillar, PROFILE)


def post(hook: str, body: str) -> dict:
    return {"hook": hook, "body": body, "cta": "Tell us in the comments.", "hashtags": ["#TaskNest"]}


def test_pillars_are_classified():
    assert {k: pillar_kind(p, PROFILE) for k, p in PILLARS.items()} == {k: k for k in PILLARS}


# ─── The TaskNest regression ────────────────────────────────────────────────

def test_tasknest_draft_reflects_the_problem_pillar():
    assert aligned(TASKNEST_DRAFT, "problem") == (True, "problem")  # by substance — it never says "problem"/"solve"
    assert "problem" not in assemble(TASKNEST_DRAFT).lower() and "solve" not in assemble(TASKNEST_DRAFT).lower()


def test_tasknest_draft_has_no_pillar_warning_in_full_validation():
    meta = {"product_name": "TaskNest", "pillar": "The problem we solve", **pillar_context(PILLARS["problem"], PROFILE)}
    report = validate_post({**TASKNEST_DRAFT, "alternative_hooks": ["a b c", "d e f", "g h i"], "pillar": "The problem we solve",
                            "claims": [], "strategy_alignment": "x", "limitations": []},
                           ["P:problem_solved"], str(PROFILE) + TASKNEST_DRAFT["body"], meta, platform_policy())
    assert not any("does not clearly reflect" in w for w in report["warnings"])


# ─── Representative examples for each pillar: paraphrase passes, mismatch warns ─────────

@pytest.mark.parametrize("kind, matching, mismatched", [
    ("problem",
     post("Freelancers: how many hours a week go to chasing deadlines across scattered tools?",
          "Juggling projects and tasks leaves less time for real design work. TaskNest keeps projects organized."),
     post("Meet TaskNest.", "Task boards. Deadline reminders. Project tracking.")),
    ("value",
     post("Less time organizing work. More time delivering projects.", "That is what TaskNest is for."),
     post("Meet TaskNest.", "Task boards and deadline reminders, built for freelance designers.")),
    ("features",
     post("Inside TaskNest for freelance designers.", "Task boards for every client.\nDeadline reminders before due dates."),
     post("Less admin, more design.", "Spend less time organizing work and more time delivering projects with TaskNest.")),
    ("differentiator",
     post("Simple tracking designed for independent freelancers.", "TaskNest keeps every client job in one place."),
     post("Less admin, more design.", "Task boards and deadline reminders for freelance designers.")),
])
def test_each_pillar(kind, matching, mismatched):
    ok, _ = aligned(matching, kind)
    assert ok, f"{kind}: grounded paraphrase should pass"
    ok, _ = aligned(mismatched, kind)
    assert not ok, f"{kind}: mismatched post should still warn"


def test_problem_pillar_needs_problem_framing_not_just_shared_words():
    # The problem's own words without any problem framing in the opening: still a warning.
    listing = post("TaskNest for freelance designers.", "Organize projects, track tasks and deadlines in one app.")
    assert aligned(listing, "problem") == (False, "problem")


def test_product_and_audience_words_never_count_as_evidence():
    generic = post("TaskNest for freelance designers.", "TaskNest is built for freelance designers.")
    for kind in PILLARS:
        assert aligned(generic, kind)[0] is False, kind


def test_without_pillar_details_only_the_literal_check_applies():
    full, opening = assemble(TASKNEST_DRAFT), lead(TASKNEST_DRAFT["hook"], TASKNEST_DRAFT["body"])
    assert pillar_alignment(full, opening, "The problem we solve") == (False, "no pillar details")
    assert pillar_alignment(full + " That is the problem we solve.", opening, "The problem we solve") == (True, "literal")
