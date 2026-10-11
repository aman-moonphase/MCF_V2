"""Tests for Phase 9 LangGraph workflow orchestration.

Verifies:
1. Node execution order & stage transitions.
2. Conditional routing and prerequisite halting (profile, competitor, strategy).
3. Evidence handling & claim-evidence traceability.
4. Evaluation version consistency.
5. Strict human review boundary (never auto-approves or auto-publishes).
6. Explicit human approval workflow completion.
7. Cross-user isolation.
"""

from uuid import UUID
import pytest

from app.ai.graphs.product_workflow_graph import (
    ProductWorkflowState,
    build_product_workflow_graph,
    get_product_workflow_graph,
)
from app.core.config import settings
from tests.test_generate_content import ready_project, make_product, generate
from tests.test_promotion_strategy import other_client  # noqa: F401


@pytest.fixture(autouse=True)
def demo_mode(monkeypatch):
    monkeypatch.setattr(settings, "AI_PROVIDER", "demo")
    monkeypatch.setattr(settings, "AI_SINGLE_ATTEMPT", True)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Pure LangGraph State & Routing Invariant Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_graph_state_machine_execution_order_and_review_boundary():
    """Graph executes stages in strict sequence and pauses at the human review boundary."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "product_id": "prod-123",
        "user_id": 1,
        "sources_grounded": True,
        "source_evidence": {"S1": "Source doc 1"},
        "product_profile": {"name": "LedgerLeaf", "value_proposition": "Fast bookkeeping"},
        "profile_version": 1,
        "profile_approved": True,
        "competitor_comparison": {"summary": "Differentiated by WhatsApp invoices"},
        "competitor_version": 1,
        "competitors_approved": True,
        "promotion_strategy": {"content_pillars": [{"name": "Tax Tips", "purpose": "Educate"}]},
        "strategy_version": 1,
        "strategy_approved": True,
        "content_type": "Social Post",
        "generated_post": {
            "hook": "Stop wasting hours on bookkeeping.",
            "body": "LedgerLeaf helps freelance designers finish invoicing in minutes.",
            "cta": "Try LedgerLeaf free.",
            "hashtags": ["#freelance", "#bookkeeping"],
            "claims": [
                {"text": "LedgerLeaf is a bookkeeping app", "kind": "product_fact", "refs": ["P:value_proposition"]},
                {"text": "Built for freelance designers", "kind": "product_fact", "refs": ["S1"]},
            ],
        },
        "content_version": 1,
        "evaluation": {"overall": {"level": "pass", "label": "Pass"}},
        "evaluation_version": 1,
        "review_approved": False,
    }

    result = await graph.ainvoke(state)

    # Invariant: stage sequence executed
    assert result["stage_history"] == [
        "source-grounding",
        "product-understanding",
        "competitor-analysis",
        "promotion-strategy",
        "generate-content",
        "evaluate-improve",
        "review-approval",
    ]

    # Invariant: strictly pauses at human review boundary
    assert result["status"] == "paused_at_approval_boundary"
    assert result["current_stage"] == "review-approval"
    assert result["review_approved"] is False
    assert "Awaiting explicit human review and approval" in result["halt_reason"]

    # Invariant: claim traceability preserved
    traceability = result["claims_traceability"]
    assert len(traceability) == 2
    assert traceability[0]["refs"] == ["P:value_proposition"]
    assert traceability[1]["refs"] == ["S1"]


@pytest.mark.asyncio
async def test_graph_halts_when_profile_unapproved():
    """Graph halts at product_understanding when profile is not approved."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "sources_grounded": True,
        "product_profile": {"name": "LedgerLeaf"},
        "profile_version": 1,
        "profile_approved": False,  # unapproved!
    }

    result = await graph.ainvoke(state)
    assert result["status"] == "halted"
    assert result["current_stage"] == "product-understanding"
    assert "requires human review and approval" in result["halt_reason"]
    # Did not advance to competitor analysis or generation
    assert "competitor-analysis" not in result["stage_history"]
    assert "generate-content" not in result["stage_history"]


@pytest.mark.asyncio
async def test_graph_halts_when_competitors_unapproved():
    """Graph halts at competitor_analysis when competitors are not approved."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "sources_grounded": True,
        "product_profile": {"name": "LedgerLeaf"},
        "profile_version": 1,
        "profile_approved": True,
        "competitor_comparison": {"summary": "Zoho comparison"},
        "competitor_version": 1,
        "competitors_approved": False,  # unapproved!
    }

    result = await graph.ainvoke(state)
    assert result["status"] == "halted"
    assert result["current_stage"] == "competitor-analysis"
    assert "requires human review and approval" in result["halt_reason"]
    assert "promotion-strategy" not in result["stage_history"]


@pytest.mark.asyncio
async def test_graph_halts_when_strategy_unapproved():
    """Graph halts at promotion_strategy when strategy is not approved."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "sources_grounded": True,
        "product_profile": {"name": "LedgerLeaf"},
        "profile_version": 1,
        "profile_approved": True,
        "competitor_comparison": {"summary": "Zoho comparison"},
        "competitor_version": 1,
        "competitors_approved": True,
        "promotion_strategy": {"content_pillars": []},
        "strategy_version": 1,
        "strategy_approved": False,  # unapproved!
    }

    result = await graph.ainvoke(state)
    assert result["status"] == "halted"
    assert result["current_stage"] == "promotion-strategy"
    assert "requires human review and approval" in result["halt_reason"]
    assert "generate-content" not in result["stage_history"]


@pytest.mark.asyncio
async def test_graph_evaluation_version_mismatch_blocks():
    """Evaluation version must strictly equal content version."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "sources_grounded": True,
        "product_profile": {"name": "LedgerLeaf"},
        "profile_approved": True,
        "competitor_comparison": {"summary": "Zoho comparison"},
        "competitors_approved": True,
        "promotion_strategy": {"content_pillars": []},
        "strategy_approved": True,
        "generated_post": {"body": "Post body", "claims": []},
        "content_version": 2,  # edited to v2
        "evaluation": {"overall": {"level": "pass"}},
        "evaluation_version": 1,  # stale evaluation for v1!
    }

    result = await graph.ainvoke(state)
    assert result["status"] == "error"
    assert result["current_stage"] == "evaluate-improve"
    assert "Evaluation is stale" in result["halt_reason"]
    assert "review-approval" not in result["stage_history"]


@pytest.mark.asyncio
async def test_graph_review_boundary_completes_upon_human_approval():
    """When human review approval is already recorded, the graph completes."""
    graph = build_product_workflow_graph()

    state: ProductWorkflowState = {
        "project_id": "proj-123",
        "sources_grounded": True,
        "product_profile": {"name": "LedgerLeaf"},
        "profile_approved": True,
        "competitor_comparison": {"summary": "Zoho comparison"},
        "competitors_approved": True,
        "promotion_strategy": {"content_pillars": []},
        "strategy_approved": True,
        "generated_post": {"body": "Post body", "claims": []},
        "content_version": 1,
        "evaluation": {"overall": {"level": "pass"}},
        "evaluation_version": 1,
        "review_approved": True,  # Approved by human!
        "approved_version": 1,
    }

    result = await graph.ainvoke(state)
    assert result["status"] == "completed"
    assert result["current_stage"] == "review-approval"
    assert result["review_approved"] is True
    assert result["halt_reason"] is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. End-to-End Orchestration API & Service Tests
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestration_api_end_to_end_flow(authenticated_client):
    """Full API execution: advances through generation, evaluation, pauses at review boundary, then approves."""
    project_id, product_id, _ = await ready_project(authenticated_client)

    # 1. Inspect status before orchestrating
    status_res = await authenticated_client.get(f"/api/workflow/orchestrate/{project_id}/status")
    assert status_res.status_code == 200, status_res.text
    initial_status = status_res.json()
    assert initial_status["project_id"] == project_id
    assert initial_status["profile_approved"] is True
    assert initial_status["competitors_approved"] is True
    assert initial_status["strategy_approved"] is True

    # 2. Run orchestration: generates post, evaluates it, and pauses at review boundary
    orch_res = await authenticated_client.post(
        f"/api/workflow/orchestrate/{project_id}",
        json={"pillar_index": 0, "campaign_instructions": "Focus on solo designers"},
    )
    assert orch_res.status_code == 200, orch_res.text
    orch_data = orch_res.json()

    assert orch_data["status"] == "paused_at_approval_boundary"
    assert orch_data["current_stage"] == "review-approval"
    assert orch_data["review_approved"] is False
    assert orch_data["content_version"] == 1
    assert orch_data["evaluation_version"] == 1
    assert orch_data["evaluation_current"] is True
    assert orch_data["generated_post"] is not None
    assert len(orch_data["claims_traceability"]) > 0

    # 3. Verify status endpoint reflects paused review boundary
    status_check = (await authenticated_client.get(f"/api/workflow/orchestrate/{project_id}/status")).json()
    assert status_check["status"] == "paused_at_approval_boundary"
    assert status_check["review_approved"] is False

    # 4. Human explicitly approves the evaluated version
    approve_res = await authenticated_client.post(
        f"/api/workflow/orchestrate/{project_id}/approve",
        json={"version": 1},
    )
    assert approve_res.status_code == 200, approve_res.text
    approved_data = approve_res.json()

    assert approved_data["status"] == "completed"
    assert approved_data["review_approved"] is True
    assert approved_data["approved_version"] == 1


@pytest.mark.asyncio
async def test_orchestration_api_refuses_cross_user_access(authenticated_client, other_client):
    """User B cannot orchestrate or read status of User A's project on either route."""
    project_id, _, _ = await ready_project(authenticated_client)

    # other_client should get 404 on legacy routes
    forbidden_run = await other_client.post(f"/api/workflow/orchestrate/{project_id}")
    assert forbidden_run.status_code == 404

    forbidden_status = await other_client.get(f"/api/workflow/orchestrate/{project_id}/status")
    assert forbidden_status.status_code == 404

    # other_client should also get 404 on project-scoped routes
    forbidden_run_proj = await other_client.post(f"/api/projects/{project_id}/orchestration")
    assert forbidden_run_proj.status_code == 404

    forbidden_status_proj = await other_client.get(f"/api/projects/{project_id}/orchestration/status")
    assert forbidden_status_proj.status_code == 404


@pytest.mark.asyncio
async def test_orchestration_api_dual_route_and_initial_status(authenticated_client):
    """A fresh project has valid initial idle status, accessible via both route conventions."""
    res = await authenticated_client.post(
        "/api/projects",
        json={"title": "Fresh Orchestration Project", "source_type": "Text Idea", "source_reference": "Idea context"},
    )
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]

    # 1. Project-scoped route: /api/projects/{id}/orchestration/status
    proj_status_res = await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")
    assert proj_status_res.status_code == 200, proj_status_res.text
    proj_status = proj_status_res.json()

    assert proj_status["project_id"] == project_id
    assert proj_status["current_stage"] == "source-grounding"
    assert proj_status["status"] == "in_progress"
    assert proj_status["review_approved"] is False
    assert proj_status["sources_grounded"] is False
    assert proj_status["content_version"] is None

    # 2. Workflow route: /api/workflow/orchestrate/{id}/status
    workflow_status_res = await authenticated_client.get(f"/api/workflow/orchestrate/{project_id}/status")
    assert workflow_status_res.status_code == 200, workflow_status_res.text
    workflow_status = workflow_status_res.json()

    # Route parity check
    assert proj_status == workflow_status


@pytest.mark.asyncio
async def test_orchestration_api_genuine_errors_handled(authenticated_client):
    """Missing project returns 404 with 'Project not found' on both routes."""
    import uuid
    missing_id = str(uuid.uuid4())

    # 1. Missing project returns 404 with 'Project not found' on both routes
    res_proj = await authenticated_client.get(f"/api/projects/{missing_id}/orchestration/status")
    assert res_proj.status_code == 404
    assert res_proj.json()["detail"] == "Project not found"

    res_wf = await authenticated_client.get(f"/api/workflow/orchestrate/{missing_id}/status")
    assert res_wf.status_code == 404
    assert res_wf.json()["detail"] == "Project not found"


@pytest.mark.asyncio
async def test_orchestration_api_unauthenticated_rejected(client):
    """Unauthenticated requests are rejected with 401 Unauthorized on both routes."""
    import uuid
    missing_id = str(uuid.uuid4())

    unauth_proj = await client.get(f"/api/projects/{missing_id}/orchestration/status")
    assert unauth_proj.status_code == 401

    unauth_wf = await client.get(f"/api/workflow/orchestrate/{missing_id}/status")
    assert unauth_wf.status_code == 401


@pytest.mark.asyncio
async def test_orchestration_api_halts_at_unapproved_understanding_like_focusflow(authenticated_client):
    """When a project with ingested sources runs orchestration, it generates profile and halts for approval."""
    # Create project and ingest source (exact FocusFlow pre-orchestration state)
    res = await authenticated_client.post(
        "/api/projects",
        json={"title": "FocusFlow Scheduler", "source_type": "Text Idea", "source_reference": "FocusFlow scheduling tool"},
    )
    assert res.status_code == 201, res.text
    project_id = res.json()["id"]

    source_content = (
        "FocusFlow is a calendar and task scheduling assistant for solo founders. "
        "It eliminates meeting fragmentation by grouping appointments into focused time blocks."
    )
    ingest_res = await authenticated_client.post(
        f"/api/projects/{project_id}/sources/ingest",
        data={"source_type": "text", "content": source_content},
    )
    assert ingest_res.status_code == 200, ingest_res.text

    # Run orchestration via project endpoint with default options (empty body / no instructions)
    orch_res = await authenticated_client.post(f"/api/projects/{project_id}/orchestration", json={"pillar_index": 0})
    assert orch_res.status_code == 200, orch_res.text
    orch_data = orch_res.json()

    # Must halt at product-understanding awaiting human approval
    assert orch_data["status"] == "halted"
    assert orch_data["current_stage"] == "product-understanding"
    assert orch_data["profile_approved"] is False
    assert orch_data["product_profile"] is not None
    assert "Human review and approval is required" in orch_data["halt_reason"]


@pytest.mark.asyncio
async def test_orchestration_api_generates_strategy_and_halts_for_approval(authenticated_client):
    """When profile and competitors are approved but strategy is ungenerated, orchestration generates strategy and halts."""
    from tests.test_promotion_strategy import make_product, approve_competitors
    project_id, product_id = await make_product(authenticated_client)
    await approve_competitors(authenticated_client, project_id, product_id, with_evidence=True)

    # Trigger orchestration: should call StrategyService.generate(product.id) without argument error and halt
    orch_res = await authenticated_client.post(f"/api/projects/{project_id}/orchestration", json={"pillar_index": 0})
    assert orch_res.status_code == 200, orch_res.text
    orch_data = orch_res.json()

    assert orch_data["status"] == "halted"
    assert orch_data["current_stage"] == "promotion-strategy"
    assert orch_data["strategy_approved"] is False
    assert orch_data["promotion_strategy"] is not None
    assert "Promotion strategy (version 1) generated" in orch_data["halt_reason"]


@pytest.mark.asyncio
async def test_orchestration_status_tracks_edited_versions_evaluations_and_approval(authenticated_client):
    """Regression test:
    1. Post v1 generated -> evaluate v1 -> orchestration status pauses at review boundary (v1).
    2. Post edited to v2 -> orchestration status moves out of pause boundary (eval stale).
    3. Evaluate v2 -> orchestration status pauses at review boundary for v2 (not v1).
    4. Post edited to v3 -> attempting to approve stale v1/v2 or unevaluated v3 fails.
    5. Evaluate v3 -> explicit human approval of v3 succeeds.
    6. Orchestration status reflects 'completed', review_approved=True, approved_version=3.
    7. Re-running orchestration preserves approved post and returns completed without mutating draft.
    """
    project_id, _, _ = await ready_project(authenticated_client)

    # 1. Generate Post v1
    gen_res = await generate(authenticated_client, project_id)
    assert gen_res["draft"]["version"] == 1

    # Check status before evaluation: in_progress at evaluate-improve
    s0 = (await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")).json()
    assert s0["content_version"] == 1
    assert s0["evaluation_version"] is None
    assert s0["evaluation_current"] is False
    assert s0["current_stage"] == "evaluate-improve"
    assert s0["status"] == "in_progress"
    assert s0["review_approved"] is False

    # Evaluate v1
    ev1 = await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": 1})
    assert ev1.status_code == 200, ev1.text

    # Status after v1 evaluation: paused at approval boundary for v1
    s1 = (await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")).json()
    assert s1["content_version"] == 1
    assert s1["evaluation_version"] == 1
    assert s1["evaluation_current"] is True
    assert s1["status"] == "paused_at_approval_boundary"
    assert s1["current_stage"] == "review-approval"
    assert s1["review_approved"] is False
    assert "v1" in s1["halt_reason"]

    # 2. Hand-edit draft to v2
    edit_v2 = await authenticated_client.patch(
        f"/api/projects/{project_id}/generated-content",
        json={"cta": "Message us to schedule your music tutor trial.", "version": 1},
    )
    assert edit_v2.status_code == 200, edit_v2.text
    assert edit_v2.json()["draft"]["version"] == 2

    # Status after v2 edit: evaluation is now stale (v1 != v2), no longer paused at approval boundary
    s2_pre = (await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")).json()
    assert s2_pre["content_version"] == 2
    assert s2_pre["evaluation_version"] == 1
    assert s2_pre["evaluation_current"] is False
    assert s2_pre["status"] == "in_progress"
    assert s2_pre["current_stage"] == "evaluate-improve"
    assert s2_pre["review_approved"] is False

    # 3. Evaluate v2
    ev2 = await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": 2})
    assert ev2.status_code == 200, ev2.text

    s2_post = (await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")).json()
    assert s2_post["content_version"] == 2
    assert s2_post["evaluation_version"] == 2
    assert s2_post["evaluation_current"] is True
    assert s2_post["status"] == "paused_at_approval_boundary"
    assert s2_post["current_stage"] == "review-approval"
    assert s2_post["review_approved"] is False
    assert "v2" in s2_post["halt_reason"]

    # 4. Hand-edit draft to v3
    edit_v3 = await authenticated_client.patch(
        f"/api/projects/{project_id}/generated-content",
        json={"body": "FocusFlow streamlines independent music tutor schedules.", "version": 2},
    )
    assert edit_v3.status_code == 200, edit_v3.text
    assert edit_v3.json()["draft"]["version"] == 3

    # Attempting to approve obsolete version 1 fails
    bad_v1 = await authenticated_client.post(
        f"/api/projects/{project_id}/orchestration/approve", json={"version": 1}
    )
    assert bad_v1.status_code in (400, 409), bad_v1.text

    # Attempting to approve obsolete version 2 fails
    bad_v2 = await authenticated_client.post(
        f"/api/projects/{project_id}/orchestration/approve", json={"version": 2}
    )
    assert bad_v2.status_code in (400, 409), bad_v2.text

    # Attempting to approve unevaluated version 3 fails
    bad_v3 = await authenticated_client.post(
        f"/api/projects/{project_id}/orchestration/approve", json={"version": 3}
    )
    assert bad_v3.status_code in (400, 409), bad_v3.text

    # 5. Evaluate v3
    ev3 = await authenticated_client.post(f"/api/projects/{project_id}/evaluation", json={"version": 3})
    assert ev3.status_code == 200, ev3.text

    # 6. Explicit human approval of v3 via orchestration approve route
    app_res = await authenticated_client.post(
        f"/api/projects/{project_id}/orchestration/approve", json={"version": 3}
    )
    assert app_res.status_code == 200, app_res.text
    app_data = app_res.json()
    assert app_data["status"] == "completed"
    assert app_data["review_approved"] is True
    assert app_data["approved_version"] == 3
    assert app_data["content_version"] == 3
    assert app_data["halt_reason"] is None

    # Check status endpoint derives authoritative completed state
    final_status = (await authenticated_client.get(f"/api/projects/{project_id}/orchestration/status")).json()
    assert final_status["status"] == "completed"
    assert final_status["review_approved"] is True
    assert final_status["approved_version"] == 3
    assert final_status["content_version"] == 3
    assert final_status["evaluation_version"] == 3
    assert final_status["evaluation_current"] is True
    assert final_status["halt_reason"] is None

    # 7. Re-running orchestration on approved project safely returns completed state without mutating post
    re_orch = await authenticated_client.post(
        f"/api/projects/{project_id}/orchestration", json={"pillar_index": 0}
    )
    assert re_orch.status_code == 200, re_orch.text
    re_data = re_orch.json()
    assert re_data["status"] == "completed"
    assert re_data["review_approved"] is True
    assert re_data["approved_version"] == 3
    assert re_data["content_version"] == 3

    # Verify draft in DB remains approved and at version 3
    draft_check = (await authenticated_client.get(f"/api/projects/{project_id}/generated-content")).json()["draft"]
    assert draft_check["version"] == 3
    assert draft_check["status"] == "approved"
    assert draft_check["approved_version"] == 3
