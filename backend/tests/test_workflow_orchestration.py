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
from tests.test_generate_content import ready_project, make_product
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
    """User B cannot orchestrate or read status of User A's project."""
    project_id, _, _ = await ready_project(authenticated_client)

    # other_client should get 404
    forbidden_run = await other_client.post(f"/api/workflow/orchestrate/{project_id}")
    assert forbidden_run.status_code == 404

    forbidden_status = await other_client.get(f"/api/workflow/orchestrate/{project_id}/status")
    assert forbidden_status.status_code == 404
