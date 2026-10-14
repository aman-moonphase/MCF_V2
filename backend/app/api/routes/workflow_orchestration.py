"""API routes for Phase 9 LangGraph workflow orchestration."""

from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.workflow_orchestration_service import WorkflowOrchestrationService

router = APIRouter()


class OrchestrateRequest(BaseModel):
    pillar_index: int = Field(default=0, ge=0, description="Selected content pillar index from approved strategy")
    campaign_instructions: Optional[str] = Field(
        default=None, max_length=1000, description="Optional campaign instructions for generation"
    )


class ReviewApprovalRequest(BaseModel):
    version: int = Field(description="Content version being reviewed and approved")


@router.post("/orchestrate/{project_id}", response_model=Dict[str, Any])
async def orchestrate_workflow(
    project_id: UUID,
    body: Optional[OrchestrateRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Executes the stateful LangGraph pipeline up to the next human review boundary or required checkpoint."""
    service = WorkflowOrchestrationService(db, user.id)
    req = body or OrchestrateRequest()
    return await service.orchestrate(
        project_id,
        pillar_index=req.pillar_index,
        campaign_instructions=req.campaign_instructions,
    )


@router.get("/orchestrate/{project_id}/status", response_model=Dict[str, Any])
async def get_orchestration_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Returns the current state of the LangGraph workflow, including claim traceability and review boundary status."""
    service = WorkflowOrchestrationService(db, user.id)
    return await service.get_state(project_id)


@router.post("/orchestrate/{project_id}/approve", response_model=Dict[str, Any])
async def approve_workflow_post(
    project_id: UUID,
    body: ReviewApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Explicit human approval of the evaluated content version. Completes the workflow."""
    service = WorkflowOrchestrationService(db, user.id)
    return await service.approve_review(project_id, body.version)


# ─────────────────────────────────────────────────────────────────────────────
# Project-scoped router: /api/projects/{project_id}/orchestration/*
# Matches MCF conventions for project-scoped stage routes
# ─────────────────────────────────────────────────────────────────────────────

project_router = APIRouter()


@project_router.post("/{project_id}/orchestration", response_model=Dict[str, Any])
async def orchestrate_project(
    project_id: UUID,
    body: Optional[OrchestrateRequest] = None,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await orchestrate_workflow(project_id, body, db, user)


@project_router.get("/{project_id}/orchestration/status", response_model=Dict[str, Any])
async def get_project_orchestration_status(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await get_orchestration_status(project_id, db, user)


@project_router.post("/{project_id}/orchestration/approve", response_model=Dict[str, Any])
async def approve_project_orchestration(
    project_id: UUID,
    body: ReviewApprovalRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    return await approve_workflow_post(project_id, body, db, user)
