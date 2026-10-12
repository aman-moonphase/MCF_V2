"""Evaluate & Improve: rule-based evaluation of the saved post, version-tied history, staleness after edits and
regeneration, the Review Approval gate, migration backfill rules, and no side effects (no content change, no AI call,
no publishing/scheduling). Demo Mode only; every external call is blocked."""
import hashlib
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

import pytest
import requests
from sqlalchemy import func, select, text

from app.ai.evaluation import EvaluationContext, RuleBasedEvaluator
from app.ai.platform_policy import platform_policy
from app.models.content_evaluation import ContentEvaluation
from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.schedule import Schedule
from app.models.workflow_stage import WorkflowStage
from tests.ai.test_pillar_alignment import PILLARS, PROFILE, TASKNEST_DRAFT
from tests.test_generate_content import gen_url, generate, ready_project
from tests.test_promotion_strategy import other_client  # noqa: F401

EVAL = "/api/projects/{}/evaluation"


# ─── Rule-based evaluator (unit) ────────────────────────────────────────────

def context(post: dict, pillar_kind: str = "problem", **overrides) -> EvaluationContext:
    full = {"alternative_hooks": ["a b c", "d e f", "g h i"], "claims": [], "strategy_alignment": "", "limitations": [],
            "pillar": PILLARS[pillar_kind]["name"], **post}
    values = dict(
        post=full, version=1, edited=False, product_name="TaskNest", profile=PROFILE,
        pillar_name=PILLARS[pillar_kind]["name"], pillar=PILLARS[pillar_kind],
        strategy={"primary_audience": PROFILE["target_audience"], "value_proposition": PROFILE["value_proposition"],
                  "messaging_direction": "Lead with \"Spend less time organizing work and more time delivering projects\"."},
        competitor={"differences": [], "similarities": [], "suggestions": [], "unresolved": []},
        validation={"issues": [], "warnings": [], "character_count": 900, "unsupported_claims": []},
        evidence={"P:key_features": "Approved profile: key features", "S1": "Project sources"}, policy=platform_policy())
    values.update(overrides)
    return EvaluationContext(**values)


def dimension(result: dict, key: str) -> dict:
    return next(d for d in result["dimensions"] if d["key"] == key)


def run(post: dict, kind: str = "problem", **overrides) -> dict:
    return RuleBasedEvaluator().evaluate(context(post, kind, **overrides))


def post(hook: str, body: str, **extra) -> dict:
    return {"hook": hook, "body": body, "cta": "Tell us in the comments.", "hashtags": ["#TaskNest"], **extra}


@pytest.mark.parametrize("kind, matching, mismatched", [
    ("problem", TASKNEST_DRAFT, post("Meet TaskNest.", "Task boards. Deadline reminders. Project tracking.")),
    ("value", post("Less time organizing work. More time delivering projects.", "That is what TaskNest is for."),
     post("Meet TaskNest.", "Task boards and deadline reminders, built for freelance designers.")),
    ("features", post("Inside TaskNest for freelance designers.", "Task boards for every client.\nDeadline reminders before due dates."),
     post("Less admin, more design.", "Spend less time organizing work and more time delivering projects with TaskNest.")),
    ("differentiator", post("Simple tracking designed for independent freelancers.", "TaskNest keeps every client job in one place."),
     post("Less admin, more design.", "Task boards and deadline reminders for freelance designers.")),
])
def test_pillar_dimension_for_all_four_pillars(kind, matching, mismatched):
    assert dimension(run(matching, kind), "pillar_alignment")["status"] == "pass"
    d = dimension(run(mismatched, kind), "pillar_alignment")
    assert d["status"] == "problem"
    (f,) = [f for f in d["findings"] if f["type"] == "problem"]
    assert f["severity"] == "medium" and f["suggestion"]  # actionable, tied to the approved profile


def test_tasknest_draft_is_ready_with_no_problems():
    result = run(TASKNEST_DRAFT, "problem", competitor=None, competitor_limited=True)
    assert result["counts"]["problems"] == 0 and result["overall"]["level"] in ("ready", "ready_with_recommendations")
    assert "Unknowns are listed but never change the result" in result["overall"]["explanation"]
    assert any("limited evidence" in f["message"] for f in dimension(result, "strategy_alignment")["findings"])


def test_grounded_and_unsupported_claims():
    claims = [
        {"text": "TaskNest has task boards", "kind": "product_fact", "refs": ["P:key_features", "S1"]},
        {"text": "TaskNest syncs with every calendar", "kind": "product_fact", "refs": []},
        {"text": "TaskNest is used by agencies", "kind": "product_fact", "refs": ["P:business_model"]},
        {"text": "Less admin, more design", "kind": "creative", "refs": []},
    ]
    d = dimension(run({**TASKNEST_DRAFT, "claims": claims}), "factual_grounding")
    problems = [f for f in d["findings"] if f["type"] == "problem"]
    assert d["status"] == "problem" and len(problems) == 2
    assert "without supporting evidence" in problems[0]["message"] and "syncs with every calendar" in problems[0]["message"]
    assert "empty in the approved profile" in problems[1]["message"]
    assert problems[1]["evidence"] == [{"ref": "P:business_model", "description": "Not in this post's evidence list"}]
    assert d["summary"].startswith("1 product claim(s) cite")
    assert any(f["type"] == "unknown" for f in d["findings"])  # what rules cannot verify is stated, not guessed


def test_validator_issues_become_confirmed_problems_with_severity():
    issues = [{"code": "unsupported_number", "message": "The post contains a figure that does not appear in the approved context."},
              {"code": "over_limit", "message": "The post is 3200 characters; the LinkedIn limit is 3000."}]
    result = run(TASKNEST_DRAFT, validation={"issues": issues, "warnings": [], "character_count": 3200, "unsupported_claims": []})
    assert dimension(result, "factual_grounding")["findings"][0]["severity"] == "high"
    assert dimension(result, "platform_readiness")["findings"][0]["severity"] == "high"
    assert result["overall"]["level"] == "not_ready"


def test_unsupported_competitive_claims_and_strategy_drift_are_flagged():
    boastful = post("TaskNest is the only tool freelancers need.", "Unlike other apps, TaskNest is faster than anything else.")
    d = dimension(run(boastful), "strategy_alignment")
    problems = [f for f in d["findings"] if f["type"] == "problem"]
    assert len(problems) >= 2 and all("not established by the approved competitor analysis" in f["message"] for f in problems)
    assert run(boastful)["overall"]["level"] == "needs_improvement"


def test_audience_value_and_readability_are_recommendations_not_problems():
    vague = post("Meet TaskNest.", "It is an app. " + " ".join(["This sentence keeps going with many words"] * 6) + ".")
    result = run(vague, "features")
    audience = dimension(result, "audience_positioning")
    assert {f["type"] for f in audience["findings"]} == {"recommendation"}
    assert any("value proposition" in f["message"] for f in audience["findings"])
    assert any("Long sentence" in f["message"] for f in dimension(result, "readability")["findings"])


def test_no_scores_or_predictions():
    blob = json.dumps(run(TASKNEST_DRAFT)).lower()
    for invented in ("score", "engagement rate", "predicted", "benchmark", "%"):
        assert invented not in blob.replace("no scores", "").replace("does not predict engagement", "")


# ─── API: evaluate, history, staleness ─────────────────────────────────────

def post_fingerprint(row: GeneratedContent) -> str:
    return hashlib.sha256(json.dumps([row.content, row.version, row.validation, row.usage, row.status, row.edited,
                                      row.context_snapshot, row.approved_version], sort_keys=True, default=str).encode()).hexdigest()


async def saved_post(project_id: str) -> GeneratedContent:
    from tests.conftest import TestingSessionLocal
    async with TestingSessionLocal() as fresh:
        return (await fresh.execute(select(GeneratedContent).where(GeneratedContent.project_id == UUID(project_id)))).scalar_one()


@pytest.mark.asyncio
async def test_new_projects_have_the_stage_between_generate_and_review(authenticated_client):
    res = await authenticated_client.post("/api/projects", json={"title": "t", "source_type": "Text Idea", "source_reference": "x"})
    stages = [s["stage_type"] for s in res.json()["stages"]]
    assert stages[-3:] == ["generate-content", "evaluate-improve", "review-approval"]
    assert [s["label"] for s in res.json()["stages"]][-2] == "Evaluate & Improve"


@pytest.mark.asyncio
async def test_evaluate_saved_version_without_changing_it(authenticated_client, db_session, monkeypatch):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    state = (await authenticated_client.get(EVAL.format(project_id))).json()
    assert state["status"] == "not_evaluated" and state["can_proceed"] is False and state["history"] == []

    before = post_fingerprint(await saved_post(project_id))
    schedules = (await db_session.execute(select(func.count(Schedule.id)))).scalar()

    def no_provider():
        raise AssertionError("Evaluation must not use an AI provider.")

    def no_network(*args, **kwargs):
        raise AssertionError("Evaluation must not make outbound requests.")

    monkeypatch.setattr("app.ai.providers.factory.get_configured_provider", no_provider)
    monkeypatch.setattr(requests.sessions.Session, "request", no_network)
    res = await authenticated_client.post(EVAL.format(project_id), json={"version": 1})
    assert res.status_code == 200, res.text
    state = res.json()
    assert state["status"] == "current" and state["can_proceed"] is True
    ev = state["evaluation"]
    assert ev["content_version"] == 1 and ev["evaluator"] == "rules-v1" and ev["mode"] == "rule-based"
    assert {d["key"] for d in ev["result"]["dimensions"]} == {"pillar_alignment", "factual_grounding", "audience_positioning",
                                                              "readability", "platform_readiness", "strategy_alignment"}
    assert "not an AI judgment" in ev["result"]["about"]
    assert post_fingerprint(await saved_post(project_id)) == before  # post untouched
    assert (await db_session.execute(select(func.count(Schedule.id)))).scalar() == schedules  # nothing scheduled
    assert (await saved_post(project_id)).status == "draft"  # nothing approved or published


@pytest.mark.asyncio
async def test_edit_makes_evaluation_stale_and_history_is_kept(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.post(EVAL.format(project_id), json={"version": 1})
    edited = await authenticated_client.patch(gen_url(project_id), json={"cta": "Message us to try LedgerLeaf.", "version": 1})
    assert edited.status_code == 200
    state = (await authenticated_client.get(EVAL.format(project_id))).json()
    assert state["status"] == "stale" and state["can_proceed"] is False and "version 2" in state["reason"]
    assert (await authenticated_client.post(EVAL.format(project_id), json={"version": 1})).status_code == 409  # old version
    again = (await authenticated_client.post(EVAL.format(project_id), json={"version": 2})).json()
    assert again["status"] == "current" and again["evaluation"]["content_version"] == 2
    assert [h["content_version"] for h in again["history"]] == [2, 1]  # both kept, newest first


@pytest.mark.asyncio
async def test_regeneration_makes_evaluation_stale(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    await authenticated_client.post(EVAL.format(project_id), json={"version": 1})
    await generate(authenticated_client, project_id, pillar_index=1)
    state = (await authenticated_client.get(EVAL.format(project_id))).json()
    assert state["status"] == "stale" and state["draft"]["version"] == 2


@pytest.mark.asyncio
async def test_no_post_yet(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    assert (await authenticated_client.get(EVAL.format(project_id))).json()["status"] == "no_draft"
    assert (await authenticated_client.post(EVAL.format(project_id), json={"version": 1})).status_code == 409


# ─── Review Approval gate ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_approval_requires_a_current_evaluation(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    approve = lambda v: authenticated_client.post(f"{gen_url(project_id)}/approve", json={"version": v})  # noqa: E731

    missing = await approve(1)
    assert missing.status_code == 409 and "Evaluate the saved post (version 1)" in missing.json()["detail"]
    await authenticated_client.post(EVAL.format(project_id), json={"version": 1})
    await authenticated_client.patch(gen_url(project_id), json={"cta": "Message us to try LedgerLeaf.", "version": 1})
    stale = await approve(2)
    assert stale.status_code == 409 and "Re-evaluate" in stale.json()["detail"]
    await authenticated_client.post(EVAL.format(project_id), json={"version": 2})
    ok = await approve(2)
    assert ok.status_code == 200 and ok.json()["draft"]["status"] == "approved"  # explicit human approval still required


@pytest.mark.asyncio
async def test_stage_transitions_need_a_current_evaluation(authenticated_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    stage = lambda t, s: authenticated_client.patch(f"/api/projects/{project_id}/stages/{t}", json={"status": s})  # noqa: E731
    assert (await stage("evaluate-improve", "In Progress")).status_code == 200
    assert (await stage("evaluate-improve", "Completed")).status_code == 409
    assert (await stage("review-approval", "In Progress")).status_code == 409
    await authenticated_client.post(EVAL.format(project_id), json={"version": 1})
    assert (await stage("evaluate-improve", "Completed")).status_code == 200
    assert (await stage("review-approval", "In Progress")).status_code == 200


@pytest.mark.asyncio
async def test_other_users_cannot_evaluate(authenticated_client, other_client):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    assert (await other_client.get(EVAL.format(project_id))).status_code == 404
    assert (await other_client.post(EVAL.format(project_id), json={"version": 1})).status_code == 404


# ─── Completed / approved / legacy projects are unaffected ─────────────────

@pytest.mark.asyncio
async def test_projects_completed_before_the_stage_are_untouched(authenticated_client, db_session):
    project_id, _, _ = await ready_project(authenticated_client)
    await generate(authenticated_client, project_id)
    # Simulate a project approved and completed before Evaluate & Improve existed: no evaluate-improve row.
    pid = UUID(project_id)
    await db_session.execute(text("DELETE FROM workflow_stages WHERE project_id = :p AND stage_type = 'evaluate-improve'"), {"p": pid})
    await db_session.execute(text("UPDATE generated_contents SET status = 'approved', approved_version = version WHERE project_id = :p"), {"p": pid})
    await db_session.execute(text("UPDATE workflow_stages SET status = 'Completed' WHERE project_id = :p"), {"p": pid})
    await db_session.execute(text("UPDATE projects SET status = 'Completed' WHERE id = :p"), {"p": pid})
    await db_session.commit()
    before = post_fingerprint(await saved_post(project_id))

    state = (await authenticated_client.get(EVAL.format(project_id))).json()
    assert state["status"] == "not_applicable" and "completed before Evaluate & Improve" in state["reason"]
    assert (await authenticated_client.post(EVAL.format(project_id), json={"version": 1})).status_code == 409
    project = (await authenticated_client.get(f"/api/projects/{project_id}")).json()
    assert "evaluate-improve" not in [s["stage_type"] for s in project["stages"]] and project["status"] == "Completed"
    assert all(s["status"] == "Completed" for s in project["stages"])
    assert post_fingerprint(await saved_post(project_id)) == before
    assert (await db_session.execute(select(func.count(ContentEvaluation.id)).where(ContentEvaluation.project_id == pid))).scalar() == 0


@pytest.mark.asyncio
async def test_legacy_projects_are_untouched(authenticated_client, db_session, test_user):
    project = Project(title="Legacy", source_type="Text Idea", source_reference="x", user_id=test_user.id)
    db_session.add(project)
    await db_session.commit()
    for key in ("source-grounding", "content-type", "final-script", "review-approval"):
        db_session.add(WorkflowStage(project_id=project.id, stage_type=key, status="Locked"))
    await db_session.commit()
    state = (await authenticated_client.get(EVAL.format(project.id))).json()
    assert state["status"] == "not_applicable" and "legacy" in state["reason"]
    stages = (await authenticated_client.get(f"/api/projects/{project.id}")).json()["stages"]
    assert [s["stage_type"] for s in stages] == ["source-grounding", "content-type", "final-script", "review-approval"]
    ok = await authenticated_client.patch(f"/api/projects/{project.id}/stages/review-approval", json={"status": "Completed"})
    assert ok.status_code == 200  # the generic legacy step is unchanged


# ─── Migration backfill rules ───────────────────────────────────────────────

def backfill_sql() -> str:
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "e5f6a7b8c9d0_evaluate_improve.py"
    spec = importlib.util.spec_from_file_location("evaluate_improve_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.BACKFILL_EVALUATE_STAGE_SQL


@pytest.mark.asyncio
async def test_migration_adds_the_stage_only_to_in_progress_product_projects(db_session, test_user):
    product = Product(name="Backfill Co", user_id=test_user.id)
    db_session.add(product)
    await db_session.commit()

    async def make(title, stages, project_status="Draft", post_status=None):
        project = Project(title=title, source_type="Text Idea", source_reference="x", user_id=test_user.id,
                          status=project_status, product_id=product.id)
        db_session.add(project)
        await db_session.commit()
        for key, status_ in stages.items():
            db_session.add(WorkflowStage(project_id=project.id, stage_type=key, status=status_))
        if post_status:
            db_session.add(GeneratedContent(project_id=project.id, product_id=product.id, content_type="Social Post",
                                            platform="linkedin", content={}, status=post_status, version=1))
        await db_session.commit()
        return project.id

    early = await make("early", {"product-understanding": "In Progress", "generate-content": "Locked", "review-approval": "Locked"})
    generated = await make("generated", {"product-understanding": "Completed", "generate-content": "Completed",
                                         "review-approval": "Locked"}, post_status="draft")
    completed = await make("completed", {"product-understanding": "Completed", "generate-content": "Completed",
                                         "review-approval": "Completed"}, project_status="Completed", post_status="approved")
    approved_only = await make("approved", {"product-understanding": "Completed", "generate-content": "Completed",
                                            "review-approval": "In Progress"}, post_status="approved")
    legacy = await make("legacy", {"content-selection": "Locked", "review-approval": "Locked"})
    before = {r[0]: r[1] for r in (await db_session.execute(text("SELECT id::text || stage_type, status FROM workflow_stages"))).all()}

    await db_session.execute(text(backfill_sql()))
    await db_session.execute(text(backfill_sql()))  # idempotent
    await db_session.commit()

    rows = (await db_session.execute(text("SELECT project_id, status FROM workflow_stages WHERE stage_type = 'evaluate-improve'"))).all()
    added = {r[0]: r[1] for r in rows}
    assert added.get(early) == "Locked" and added.get(generated) == "In Progress"
    for untouched in (completed, approved_only, legacy):
        assert untouched not in added
    after = {r[0]: r[1] for r in (await db_session.execute(text("SELECT id::text || stage_type, status FROM workflow_stages"))).all()}
    assert {k: v for k, v in after.items() if k in before} == before  # no existing status changed


@pytest.mark.asyncio
async def test_evaluation_reflects_persona_and_tone(authenticated_client):
    """Evaluate & Improve incorporates audience_persona and editorial_tone in evaluation context."""
    project_id, _, _ = await ready_project(authenticated_client)
    gen_res = await authenticated_client.post(
        f"/api/projects/{project_id}/generated-content",
        json={
            "pillar_index": 0,
            "audience_persona": "Segment: Freelancers",
            "editorial_tone": "bold",
        },
    )
    assert gen_res.status_code == 200

    eval_res = await authenticated_client.post(
        f"/api/projects/{project_id}/evaluation",
        json={"version": 1},
    )
    assert eval_res.status_code == 200
    state = eval_res.json()
    assert state["status"] == "current"
    ev = state["evaluation"]
    aud_dim = next(d for d in ev["result"]["dimensions"] if d["key"] == "audience_positioning")
    assert "Persona: \"Segment: Freelancers\"." in aud_dim["summary"]
    assert "Tone: Bold." in aud_dim["summary"]
