"""Demo Mode must never produce canned content unrelated to the project."""
from unittest.mock import patch

import pytest

from app.ai.providers.demo_provider import DEMO_NOTE
from app.ai.services.ai_orchestrator import AIOrchestrator

PROJECTS = {
    "bookkeeping": (
        "Product: LedgerLeaf - a bookkeeping app for freelance designers. Features: GST invoice generation, "
        "expense categorisation, and a client payment tracker. Target users: solo designers who hate spreadsheets.",
        "LedgerLeaf",
    ),
    "gaming": (
        "Product: Starfall Arena - a co-op space shooter for mobile. Features: 4-player squads, weekly boss raids, "
        "and cross-platform saves. Target audience: casual mobile gamers aged 16-30.",
        "Starfall Arena",
    ),
    "healthcare": (
        "Product: CareNest - a medication reminder service for elderly parents. Features: pill schedules, "
        "caregiver alerts, and pharmacy refill tracking. Target users: adult children caring for parents.",
        "CareNest",
    ),
}

# Phrases from the old canned AI-coding fixtures.
FORBIDDEN = [
    "ai coding", "coding assistant", "software engineer", "developer", "boilerplate", "typist", "architect",
    "prompt engineering", "javascript", "mozilla",
]


def _all_text(value) -> str:
    if isinstance(value, dict):
        return " ".join(_all_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_all_text(v) for v in value)
    return str(value)


@pytest.mark.asyncio
@pytest.mark.parametrize("name", PROJECTS)
async def test_demo_outputs_are_about_the_project(name):
    source, product = PROJECTS[name]
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        orch = AIOrchestrator()
        content_type = await orch.run_content_type(source)
        selection = await orch.run_content_selection(source, "Carousel")
        opp = selection["opportunities"][0]
        platforms = (await orch.run_platform_strategy(source, opp, "Carousel"))["recommendations"]
        angles = (await orch.run_topic_angle(source, opp, platforms, "Carousel"))["angles"]
        strategy = (await orch.run_content_strategy(source, opp, platforms, angles[0], "Carousel"))["strategy"]
        storyboard = (await orch.run_storyboard(source, opp, platforms, angles[0], strategy, "Carousel"))["storyboard"]
        script = (await orch.run_script(source, opp, platforms, angles[0], strategy, storyboard, "Carousel"))["script"]

    everything = _all_text([content_type, selection, platforms, angles, strategy, storyboard, script])
    lowered = everything.lower()
    for phrase in FORBIDDEN:
        assert phrase not in lowered, f"Unrelated canned phrase {phrase!r} in {name} demo output"

    assert product in _all_text(selection["opportunities"][0]["title"])
    assert product in strategy["objective"]
    assert product in script["title"]
    # Facts from the source are reused; the demo label is present on reasoning fields.
    first_feature = source.split("Features: ")[1].split(",")[0]
    assert first_feature.lower() in lowered
    assert DEMO_NOTE in content_type["recommendation"]["reasoning"]
    assert DEMO_NOTE in selection["opportunities"][0]["whyInteresting"]


@pytest.mark.asyncio
async def test_demo_does_not_leak_between_projects():
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        orch = AIOrchestrator()
        game = await orch.run_content_selection(PROJECTS["gaming"][0], "Social Post")
        care = await orch.run_content_selection(PROJECTS["healthcare"][0], "Social Post")
    assert "CareNest" not in _all_text(game) and "Starfall" not in _all_text(care)


@pytest.mark.asyncio
async def test_demo_with_sparse_source_does_not_invent_details():
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        orch = AIOrchestrator()
        selection = await orch.run_content_selection("Bloomly", "Carousel")
        opp = selection["opportunities"][0]
        platforms = (await orch.run_platform_strategy("Bloomly", opp, "Carousel"))["recommendations"]
        angles = (await orch.run_topic_angle("Bloomly", opp, platforms, "Carousel"))["angles"]
        strategy = (await orch.run_content_strategy("Bloomly", opp, platforms, angles[0], "Carousel"))["strategy"]
        storyboard = (await orch.run_storyboard("Bloomly", opp, platforms, angles[0], strategy, "Carousel"))["storyboard"]
    narration = " ".join(s["narration"] for s in storyboard["scenes"])
    # With nothing to draw on, the demo asks the user for detail instead of inventing it.
    assert "Add a specific detail about Bloomly" in narration
    assert not any(ch.isdigit() for ch in narration)
