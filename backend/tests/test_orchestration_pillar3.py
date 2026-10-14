"""Pillar 3: the orchestration entry point (service + API + database), not just the graph nodes.

Demo Mode only (deterministic, no paid calls). Covers: the master graph's real order and trace, persisted progress,
halting at human gates (including the Content Type), failure -> redacted trace -> safe retry, simultaneous runs,
protection of human edits and approved posts, and idempotent re-runs.
"""
import asyncio
from uuid import UUID

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.core.config import settings
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.services.generation_service import GenerationService
from app.services.workflow_orchestration_service import WorkflowOrchestrationService
from tests.conftest import TestingSessionLocal
from tests.test_generate_content import approve_type, gen_url, ready_project
from tests.test_promotion_strategy import approve as approve_strategy
from tests.test_promotion_strategy import approve_competitors, make_product, other_client  # noqa: F401
from tests.test_promotion_strategy import generate as generate_strategy
from tests.test_promotion_strategy import url as strategy_url
from tests.test_workflow_races import attempt


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)


ORDER = ["source-grounding", "product-understanding", "competitor-analysis", "promotion-strategy",
         "generate-content", "evaluate-improve", "review-approval"]


def orch(project_id):
    return f"/api/projects/{project_id}/orchestration"


async def run(client, project_id, **body):
    res = await client.post(orch(project_id), json={"pillar_index": 0, **body})
    return res


async def status(client, project_id):
    res = await client.get(f"{orch(project_id)}/status")
    assert res.status_code == 200, res.text
    return res.json()


async def stage_statuses(client, project_id):
    res = await client.get(f"/api/projects/{project_id}")
    assert res.status_code == 200, res.text
    return {s["stage_type"]: s["status"] for s in res.json()["stages"]}


async def draft_rows(project_id):
    async with TestingSessionLocal() as session:
        return (await session.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalars().all()


# ─── The graph really runs the stages, in order, and the result is saved ────────────────────────────────

@pytest.mark.asyncio
async def test_run_follows_the_canonical_order_pauses_for_review_and_persists_progress(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    res = await run(authenticated_client, project_id)
    assert res.status_code == 200, res.text
    state = res.json()

    assert state["status"] == "paused_at_approval_boundary" and state["review_approved"] is False
    assert state["stage_history"] == ORDER, "the master graph visited the stages in the canonical order"
    assert [e["stage"] for e in state["execution_log"]][-1] == "review-approval"
    assert state["content_version"] == 1 and state["evaluation_version"] == 1 and state["evaluation_current"] is True
    assert state["last_run"]["outcome"] == "paused_for_review", "the response reports the run that just finished"

    # Persisted: a fresh status read (a refresh or a restart) reports the same place, plus the saved run trace.
    again = await status(authenticated_client, project_id)
    assert again["status"] == "paused_at_approval_boundary" and again["current_stage"] == "review-approval"
    assert again["last_run"]["outcome"] == "paused_for_review"
    assert again["last_run"]["stages_visited"] == ORDER
    stages = await stage_statuses(authenticated_client, project_id)
    assert stages["generate-content"] == "Completed" and stages["evaluate-improve"] == "Completed"
    assert stages["review-approval"] != "Completed", "nothing is approved by running the workflow"


@pytest.mark.asyncio
async def test_rerunning_is_idempotent_and_never_approves(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    first = (await run(authenticated_client, project_id)).json()
    second = (await run(authenticated_client, project_id)).json()
    assert second["status"] == "paused_at_approval_boundary"
    assert second["content_version"] == first["content_version"] == 1, "no new post version from a re-run"
    assert second["evaluation_version"] == 1
    rows = await draft_rows(project_id)
    assert len(rows) == 1 and rows[0].status == "draft" and rows[0].approved_version is None


# ─── Human gates stop the run; the workflow never decides for the person ───────────────────────────────

@pytest.mark.asyncio
async def test_missing_sources_is_an_error_state_that_creates_nothing(authenticated_client):
    created = await authenticated_client.post("/api/projects", json={"title": "No sources", "source_type": "Text Idea", "source_reference": "x"})
    project_id = created.json()["id"]
    res = await run(authenticated_client, project_id)
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["status"] == "error" and "source" in state["halt_reason"].lower()
    assert state["product_profile"] is None and state["generated_post"] is None
    assert (await status(authenticated_client, project_id))["last_run"]["outcome"] == "error"


@pytest.mark.asyncio
async def test_unapproved_profile_halts_and_a_second_run_does_not_duplicate_it(authenticated_client):
    created = await authenticated_client.post("/api/projects", json={"title": "Gate", "source_type": "Text Idea", "source_reference": "x"})
    project_id = created.json()["id"]
    await authenticated_client.post(f"/api/projects/{project_id}/sources/ingest",
                                    data={"source_type": "text", "content": "FocusFlow schedules focused time blocks for solo founders."})
    one = (await run(authenticated_client, project_id)).json()
    two = (await run(authenticated_client, project_id)).json()
    for state in (one, two):
        assert state["status"] == "halted" and state["current_stage"] == "product-understanding"
        assert state["profile_approved"] is False and state["generated_post"] is None
    assert one["product_id"] == two["product_id"] and one["profile_version"] == two["profile_version"] == 1
    assert one["stage_history"] == ["source-grounding", "product-understanding"]


@pytest.mark.asyncio
async def test_content_type_is_a_human_decision_the_run_waits_for(authenticated_client):
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id)
    s = await generate_strategy(authenticated_client, product_id)
    assert (await approve_strategy(authenticated_client, project_id, product_id, s["version"])).status_code == 200

    halted = (await run(authenticated_client, project_id)).json()
    assert halted["status"] == "halted" and halted["current_stage"] == "content-type"
    assert "Content Type" in halted["halt_reason"]
    assert halted["generated_post"] is None and (await draft_rows(project_id)) == []
    assert (await stage_statuses(authenticated_client, project_id))["content-type"] != "Completed", "the run did not approve it"

    await approve_type(authenticated_client, project_id)
    paused = (await run(authenticated_client, project_id)).json()
    assert paused["status"] == "paused_at_approval_boundary" and paused["content_version"] == 1


# ─── Failure, retry, concurrency ───────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_failure_is_recorded_without_secrets_and_a_retry_creates_exactly_one_post(authenticated_client, monkeypatch):
    project_id, _, _ = await ready_project(authenticated_client)
    original = GenerationService.generate
    calls = {"n": 0}

    async def flaky(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise HTTPException(status_code=500, detail="provider failed with key sk-proj-abcdefghijklmnopqrstuvwxyz0123456789")
        return await original(self, *args, **kwargs)

    monkeypatch.setattr(GenerationService, "generate", flaky)

    failed = await run(authenticated_client, project_id)
    assert failed.status_code == 500
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz" not in failed.text

    trace = (await status(authenticated_client, project_id))["last_run"]
    assert trace["outcome"] == "failed" and "sk-proj-abcdefghijklmnopqrstuvwxyz" not in str(trace)
    assert (await draft_rows(project_id)) == [], "a failed run leaves no half-saved post"

    retry = (await run(authenticated_client, project_id)).json()
    assert retry["status"] == "paused_at_approval_boundary" and retry["content_version"] == 1
    rows = await draft_rows(project_id)
    assert len(rows) == 1 and rows[0].version == 1
    assert (await status(authenticated_client, project_id))["last_run"]["outcome"] == "paused_for_review"


@pytest.mark.asyncio
async def test_simultaneous_runs_produce_one_post_and_one_evaluation(authenticated_client, test_user):
    user_id = test_user.id
    project_id, _, _ = await ready_project(authenticated_client)

    async def orchestrate(session, uid):
        return await WorkflowOrchestrationService(session, uid).orchestrate(UUID(project_id))

    results = await asyncio.gather(attempt(user_id, orchestrate), attempt(user_id, orchestrate), attempt(user_id, orchestrate))
    assert not [r for r in results if r[0] != "ok"], f"every request should succeed cleanly: {results}"
    assert {r[1]["status"] for r in results} == {"paused_at_approval_boundary"}
    rows = await draft_rows(project_id)
    assert len(rows) == 1 and rows[0].version == 1, "waiting runs reused the saved post instead of generating again"
    async with TestingSessionLocal() as session:
        evaluations = (await session.execute(select(func.count(ContentEvaluation.id)).where(
            ContentEvaluation.project_id == UUID(project_id)))).scalar()
    assert evaluations == 1


# ─── Protecting people's work ──────────────────────────────────────────────────────────────────────────

async def change_and_reapprove_strategy(client, project_id, product_id, strategy, text):
    patched = await client.patch(strategy_url(product_id), json={"strategy": {"audience": {**strategy["strategy"]["audience"], "messaging_direction": text}}})
    assert patched.status_code == 200, patched.text
    version = patched.json()["version"]
    assert (await approve_strategy(client, project_id, product_id, version)).status_code == 200
    await approve_type(client, project_id)
    return version


@pytest.mark.asyncio
async def test_a_stale_post_the_user_edited_is_not_regenerated(authenticated_client):
    project_id, product_id, strategy = await ready_project(authenticated_client)
    v1 = (await run(authenticated_client, project_id)).json()
    assert v1["content_version"] == 1

    edited_cta = "Message us today to book a 15-minute walkthrough."
    edit = await authenticated_client.patch(gen_url(project_id), json={"cta": edited_cta, "version": 1})
    assert edit.status_code == 200, edit.text
    assert edit.json()["draft"]["version"] == 2

    await change_and_reapprove_strategy(authenticated_client, project_id, product_id, strategy, "Lead with the time saved every week.")

    halted = (await run(authenticated_client, project_id)).json()
    assert halted["status"] == "halted" and halted["current_stage"] == "generate-content"
    assert "NOT regenerated" in halted["halt_reason"]
    assert halted["content_version"] == 2

    saved = (await draft_rows(project_id))[0]
    assert saved.version == 2 and saved.edited is True and saved.content["cta"] == edited_cta, "the edit survived"


@pytest.mark.asyncio
async def test_an_unedited_stale_draft_is_regenerated_for_the_new_strategy(authenticated_client):
    project_id, product_id, strategy = await ready_project(authenticated_client)
    await run(authenticated_client, project_id)
    new_version = await change_and_reapprove_strategy(authenticated_client, project_id, product_id, strategy, "Lead with fewer manual steps.")

    paused = (await run(authenticated_client, project_id)).json()
    assert paused["status"] == "paused_at_approval_boundary" and paused["content_version"] == 2
    saved = (await draft_rows(project_id))[0]
    assert saved.context_snapshot["strategy_version"] == new_version, "the new draft used the newly approved strategy"


@pytest.mark.asyncio
async def test_an_approved_post_is_never_overwritten_by_a_later_run(authenticated_client):
    project_id, product_id, strategy = await ready_project(authenticated_client)
    await run(authenticated_client, project_id)
    approved = await authenticated_client.post(f"{orch(project_id)}/approve", json={"version": 1})
    assert approved.status_code == 200, approved.text
    before = (await draft_rows(project_id))[0]
    snapshot = (before.version, dict(before.content), before.approved_version)

    await change_and_reapprove_strategy(authenticated_client, project_id, product_id, strategy, "A different direction entirely.")
    after_run = (await run(authenticated_client, project_id)).json()
    assert after_run["status"] == "completed" and after_run["review_approved"] is True

    after = (await draft_rows(project_id))[0]
    assert (after.version, dict(after.content), after.approved_version) == snapshot
    assert after.status == "approved"


@pytest.mark.asyncio
async def test_orchestration_is_isolated_between_users(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    assert (await other_client.post(orch(project_id), json={"pillar_index": 0})).status_code == 404
    assert (await other_client.get(f"{orch(project_id)}/status")).status_code == 404
    assert (await other_client.post(f"{orch(project_id)}/approve", json={"version": 1})).status_code == 404
