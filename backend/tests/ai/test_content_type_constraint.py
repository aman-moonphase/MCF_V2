"""The approved content type is a hard constraint, enforced in backend validation (not only prompts)."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai import content_types as ct
from app.ai.schemas import PlatformStrategyOutput
from app.ai.services.ai_orchestrator import AIOrchestrator

SOURCE = (
    "Product: LedgerLeaf - a bookkeeping app for freelance designers in India. "
    "Features: auto-import of UPI and bank transactions, GST invoice generation, expense categorisation, "
    "quarterly advance-tax reminders, and a client payment tracker. "
    "Target users: solo designers and small studios who hate spreadsheets."
)


# ─── Canonical values ────────────────────────────────────────────────────────

def test_exactly_six_supported_types():
    assert ct.CONTENT_TYPES == ("Video", "Image", "Carousel", "Article", "Newsletter", "Social Post")


@pytest.mark.parametrize("raw, expected", [
    ("Carousel", "Carousel"), ("carousel", "Carousel"), (" social   post ", "Social Post"),
    ("Reel", None), ("Carousels", None), ("Blog", None), ("", None), (None, None),
])
def test_normalize_content_type(raw, expected):
    assert ct.normalize_content_type(raw) == expected


@pytest.mark.parametrize("approved, text, conflict", [
    ("Carousel", "Carousel on LinkedIn", False),
    ("Carousel", "Image carousel", False),
    ("Carousel", "Long-form video", True),
    ("Carousel", "Instagram Reel", True),
    ("Social Post", "Text social post on X (Twitter)", False),
    ("Social Post", "Thread", False),
    ("Social Post", "Carousel", True),
    ("Social Post", "Short-form video", True),
    ("Video", "Short-form vertical video", False),
    ("Video", "PDF slide deck", True),
    ("Newsletter", "Email newsletter", False),
    ("Article", "Long-form article on the blog", False),
    ("Image", "Single image post with caption", False),
])
def test_format_conflicts(approved, text, conflict):
    assert bool(ct.format_conflicts(approved, text)) is conflict


# ─── Per-stage validators ────────────────────────────────────────────────────

def test_content_selection_rejects_other_types():
    assert ct.check_opportunities("Carousel", [{"id": "1", "content_type": "Carousel"}]) is None
    assert "Video" in ct.check_opportunities("Carousel", [{"id": "1", "content_type": "Video"}])


def test_platform_strategy_rejects_video_for_carousel():
    ok = [{"platform": "LinkedIn", "recommendedFormat": "LinkedIn carousel"}]
    bad = ok + [{"platform": "YouTube", "recommendedFormat": "Long-form video"}]
    assert ct.check_platform_recommendations("Carousel", ok) is None
    assert "YouTube" in ct.check_platform_recommendations("Carousel", bad)


def test_topic_angle_rejects_format_switching_angle():
    assert ct.check_topic_angles("Social Post", [{"id": "a", "angle": "Educational"}]) is None
    assert ct.check_topic_angles("Social Post", [{"id": "a", "angle": "Behind-the-scenes video"}])


def test_strategy_checks_format_and_adaptations():
    assert ct.check_strategy("Carousel", {"format": "Carousel", "platformAdaptations": [{"platform": "LinkedIn", "format": "Carousel"}]}) is None
    assert ct.check_strategy("Carousel", {"format": "Video series", "platformAdaptations": []})
    assert ct.check_strategy("Carousel", {"format": "Carousel", "platformAdaptations": [{"platform": "YouTube", "format": "Video"}]})


def test_storyboard_rejects_wrong_structure():
    carousel = {"scenes": [{"order": 1, "transition": "Swipe"}, {"order": 2, "transition": "None"}]}
    assert ct.check_storyboard("Carousel", carousel) is None
    assert ct.check_storyboard("Carousel", {"scenes": [{"order": 1, "transition": "Cut to close-up"}]})
    assert ct.check_storyboard("Social Post", {"scenes": [{"order": 1, "transition": "Swipe"}]})
    assert ct.check_storyboard("Social Post", {"scenes": [{"order": 1, "transition": "Fade out"}]})
    assert ct.check_storyboard("Video", {"scenes": [{"order": 1, "transition": "Cut"}]}) is None


def test_script_rejects_wrong_format():
    assert ct.check_script("Social Post", {"format": "Text social post"}) is None
    assert ct.check_script("Social Post", {"format": "Carousel"})


# ─── Enforced inside the LangGraph workflow ──────────────────────────────────

def _platforms(fmt: str) -> PlatformStrategyOutput:
    return PlatformStrategyOutput(recommendations=[{
        "id": "plat-1", "projectId": "p", "platform": "LinkedIn", "suitability": 90, "reasoning": "r",
        "recommendedFormat": fmt, "recommendedLength": "l", "audience": "a", "tone": "t", "priority": "Recommended",
    }])


@pytest.mark.asyncio
async def test_violating_output_is_regenerated_with_feedback():
    provider = MagicMock()
    provider.generate_text = AsyncMock(return_value="analysis")
    provider.generate_structured = AsyncMock(side_effect=[_platforms("Long-form video"), _platforms("Carousel on LinkedIn")])

    with patch("app.ai.nodes.platform_strategy_nodes.get_provider", return_value=provider):
        result = await AIOrchestrator().run_platform_strategy(SOURCE, {"title": "t", "summary": "s"}, "Carousel")

    assert result["recommendations"][0]["recommendedFormat"] == "Carousel on LinkedIn"
    second_prompt = provider.generate_structured.call_args_list[1].args[0]
    assert "PREVIOUS ATTEMPT WAS REJECTED" in second_prompt
    assert "incompatible with the approved content type 'Carousel'" in second_prompt


@pytest.mark.asyncio
async def test_persistently_violating_output_is_never_accepted():
    provider = MagicMock()
    provider.generate_text = AsyncMock(return_value="analysis")
    provider.generate_structured = AsyncMock(return_value=_platforms("YouTube video"))

    with patch("app.ai.nodes.platform_strategy_nodes.get_provider", return_value=provider):
        with pytest.raises(RuntimeError, match="incompatible with the approved content type"):
            await AIOrchestrator().run_platform_strategy(SOURCE, {"title": "t", "summary": "s"}, "Carousel")


@pytest.mark.asyncio
async def test_orchestrator_rejects_unsupported_approved_type():
    with pytest.raises(ValueError, match="not a supported content type"):
        await AIOrchestrator().run_content_selection(SOURCE, "Reel")


@pytest.mark.asyncio
@pytest.mark.parametrize("content_type", ct.CONTENT_TYPES)
async def test_demo_pipeline_stays_within_approved_type(content_type):
    """Full demo pipeline per type: every stage passes the backend constraint validators."""
    with patch("app.core.config.settings.AI_PROVIDER", "demo"):
        orch = AIOrchestrator()
        selection = await orch.run_content_selection(SOURCE, content_type)
        opp = selection["opportunities"][0]
        platforms = (await orch.run_platform_strategy(SOURCE, opp, content_type))["recommendations"]
        angles = (await orch.run_topic_angle(SOURCE, opp, platforms, content_type))["angles"]
        strategy = (await orch.run_content_strategy(SOURCE, opp, platforms, angles[0], content_type))["strategy"]
        storyboard = (await orch.run_storyboard(SOURCE, opp, platforms, angles[0], strategy, content_type))["storyboard"]
        storyboard["status"] = "Approved"
        script = (await orch.run_script(SOURCE, opp, platforms, angles[0], strategy, storyboard, content_type))["script"]

    assert all(o["content_type"] == content_type for o in selection["opportunities"])
    assert ct.check_platform_recommendations(content_type, platforms) is None
    assert ct.check_topic_angles(content_type, angles) is None
    assert ct.check_strategy(content_type, strategy) is None
    assert ct.check_storyboard(content_type, storyboard) is None
    assert ct.check_script(content_type, script) is None
    assert len(script["sections"]) == len(storyboard["scenes"])


# ─── API-level enforcement ───────────────────────────────────────────────────

async def _create_project(client):
    res = await client.post("/api/projects", json={"title": "LedgerLeaf", "source_type": "Text Idea", "source_reference": "LedgerLeaf"})
    assert res.status_code == 201
    return res.json()["id"]


@pytest.mark.asyncio
async def test_api_rejects_unsupported_approved_type(authenticated_client):
    project_id = await _create_project(authenticated_client)
    res = await authenticated_client.patch(
        f"/api/projects/{project_id}/stages/content-type",
        json={"status": "Completed", "data": {"approved_type": "Reel"}},
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_api_normalizes_approved_type(authenticated_client):
    project_id = await _create_project(authenticated_client)
    res = await authenticated_client.patch(
        f"/api/projects/{project_id}/stages/content-type",
        json={"status": "Completed", "data": {"approved_type": "social post"}},
    )
    assert res.status_code == 200
    assert res.json()["data"]["approved_type"] == "Social Post"


@pytest.mark.asyncio
async def test_api_rejects_legacy_invalid_stored_type(authenticated_client, db_session):
    """Data written before validation existed must not slip through to generation."""
    from uuid import UUID
    from sqlalchemy import update
    from app.models.workflow_stage import WorkflowStage

    project_id = await _create_project(authenticated_client)
    await db_session.execute(
        update(WorkflowStage)
        .where(WorkflowStage.project_id == UUID(project_id), WorkflowStage.stage_type == "content-type")
        .values(data={"approved_type": "Podcast"})
    )
    await db_session.commit()

    res = await authenticated_client.post("/api/ai/content-selection", json={"project_id": project_id})
    assert res.status_code == 400
    assert "not supported" in res.json()["detail"]
