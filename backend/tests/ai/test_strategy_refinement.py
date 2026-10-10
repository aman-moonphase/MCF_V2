"""Regression (manual StudioDesk test), Demo Mode Promotion Strategy:
- the differentiator pillar name was cut at 80 characters ("... without an int") and reused as subject area / roadmap topic;
- a "First 4 weeks" horizon had only Weeks 1-3;
- every recommendation revolved around the single differentiator instead of the value proposition.
"""
import re
from unittest.mock import patch

import pytest

from app.ai.graphs.strategy_graph import run_promotion_strategy
from app.ai.platform_policy import apply_mvp_content_type
from app.ai.providers.demo_strategy import _heading

DIFFERENTIATOR = "Offline attendance check-in helps teachers manage attendance even without an internet connection"
PROFILE = {
    "name": "StudioDesk",
    "description": "StudioDesk is a booking and invoicing app for independent yoga teachers.",
    "target_audience": "Independent yoga teachers who teach in rented studios.",
    "problem_solved": "Teachers lose time to bookings, invoicing and chasing payments.",
    "key_features": ["Class booking links", "Automatic payment reminders", "Attendance tracking", "Offline attendance check-in"],
    "value_proposition": "Spend time teaching, not chasing payments.",
    "differentiators": [DIFFERENTIATOR],
}


async def demo_strategy(profile=PROFILE):
    state = {"prompt_context": [], "allowed_refs": [f"profile:{k}" for k in profile], "corpus": str(profile), "meta": {"limited": True},
             "demo_input": {"product": profile, "comparison": None, "competitors": [], "limited": True,
                            "mvp_content_type": "Social Post"}}
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        return apply_mvp_content_type(await run_promotion_strategy(state))


def test_heading_is_the_named_feature_or_a_whole_clause():
    assert _heading(DIFFERENTIATOR, PROFILE["key_features"]) == "Offline attendance check-in"
    long = "Works with every major calendar and syncs bookings automatically across all the devices a teacher owns today"
    heading = _heading(long, [])
    assert heading == "Works with every major calendar and syncs bookings"
    assert long.startswith(heading) and len(heading) <= 60


@pytest.mark.asyncio
async def test_no_text_is_cut_mid_word_and_the_full_differentiator_is_kept():
    s = await demo_strategy()
    names = [p["name"] for p in s["content_pillars"]]
    assert "Offline attendance check-in" in names
    differentiator = next(p for p in s["content_pillars"] if p["name"] == "Offline attendance check-in")
    assert DIFFERENTIATOR in differentiator["relation_to_product"]
    assert any(DIFFERENTIATOR in a for a in s["content_direction"]["messaging_angles"])
    shown = names + s["content_direction"]["subject_areas"] + [r["topic"] for r in s["roadmap"]]
    for text in shown:
        assert not re.search(r"\bint$|\w+…$", text), text
        assert text in names  # subject areas and roadmap topics are the (complete) pillar headings


@pytest.mark.asyncio
async def test_roadmap_matches_the_planning_horizon():
    s = await demo_strategy()
    weeks = [r["timing"] for r in s["roadmap"]]
    assert weeks == ["Week 1 · main post", "Week 2 · main post", "Week 3 · main post", "Week 4 · main post"]
    assert s["cadence"]["planning_horizon"] == "First 4 weeks"
    assert [r["sequence"] for r in s["roadmap"]] == [1, 2, 3, 4]
    assert len({r["objective"] for r in s["roadmap"]}) == 4

    sparse = {k: v for k, v in PROFILE.items() if k not in ("problem_solved", "value_proposition")}
    small = await demo_strategy(sparse)
    assert small["cadence"]["planning_horizon"] == f"First {len(small['roadmap'])} weeks"


@pytest.mark.asyncio
async def test_messaging_is_balanced_around_the_value_proposition():
    s = await demo_strategy()
    value = "Spend time teaching, not chasing payments"
    assert s["audience"]["value_proposition"] == PROFILE["value_proposition"]
    assert s["audience"]["messaging_direction"].startswith(f'Lead with "{value}"')
    assert value in s["executive_summary"]["primary_recommendation"]
    assert value in s["executive_summary"]["main_opportunity"]
    assert s["content_direction"]["messaging_angles"][0] == f"Lead with: {PROFILE['value_proposition']}"
    pillars = [p["name"] for p in s["content_pillars"]]
    assert pillars == ["The problem we solve", "The time it gives back", "How it works", "Offline attendance check-in"]
    refs = [p["grounding"]["refs"] for p in s["content_pillars"]]
    assert refs == [["profile:problem_solved"], ["profile:value_proposition"], ["profile:key_features"], ["profile:differentiators"]]
    # Only one of four pillars and one roadmap week are about the differentiator.
    assert sum("offline" in r["topic"].lower() for r in s["roadmap"]) == 1


@pytest.mark.asyncio
async def test_channels_and_cadence_stay_hypotheses_and_nothing_is_invented():
    s = await demo_strategy()
    assert s["channels"][0]["channel"] == "LinkedIn"
    assert all(c["grounding"]["basis"] == "hypothesis" and c["grounding"]["confidence"] == "low" for c in s["channels"])
    assert s["cadence"]["is_hypothesis"] is True and s["cadence"]["grounding"]["basis"] == "hypothesis"
    assert all(r["grounding"]["basis"] == "hypothesis" for r in s["roadmap"])
    numbers = set(re.findall(r"\d+", str({k: v for k, v in s.items() if k not in ("roadmap", "cadence")})))
    assert numbers <= set(re.findall(r"\d+", str(PROFILE)))


@pytest.mark.asyncio
async def test_cadence_and_roadmap_are_consistent():
    """2-3 posts per week vs one roadmap item per week: each item is the week's main post, and the cadence says
    what the other posts are, so the numbers add up without inventing extra roadmap topics."""
    s = await demo_strategy()
    cadence = s["cadence"]
    assert cadence["frequency"] == "2-3 posts per week"
    assert all(r["timing"].endswith("· main post") for r in s["roadmap"])
    assert "Each roadmap week lists its main, pillar-focused post" in cadence["rationale"]
    assert "the other 1-2 posts that week stay on the same pillar" in cadence["rationale"]
    assert "for 2-3 posts per week in total" in cadence["rationale"]
    assert cadence["is_hypothesis"] is True and cadence["grounding"]["basis"] == "hypothesis"
    assert not re.search(r"(?:engagement|reach|impressions|conversion|followers)", cadence["rationale"], re.I)


def test_weekly_plan_follows_the_cadence_text():
    from app.ai.providers.demo_strategy import _weekly_plan
    assert _weekly_plan("2-3 posts per week") == ("1-2", "posts", "2-3 posts")
    assert _weekly_plan("1-2 carousels per week") == ("up to 1", "carousel", "1-2 carousels")
    assert _weekly_plan("3 posts per week") == ("2", "posts", "3 posts")
    for single in ("1 short video per week", "1 issue every two weeks", "1 article every week or two"):
        assert _weekly_plan(single) is None  # one item per week (or less): the roadmap already matches
