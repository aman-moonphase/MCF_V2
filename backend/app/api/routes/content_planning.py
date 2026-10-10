"""Calendar & content planning endpoints: plan an approved post, reschedule or cancel a planned entry.

Planning only: these endpoints record human intent on the calendar. Nothing is published, posted or queued.
Rules live in app/services/content_planning_service.py and app/services/scheduling_eligibility.py.
"""
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.schedule import (CancelPlanRequest, PlanContentRequest, PlanEligibilityResponse, RescheduleRequest,
                                  ScheduleResponse)
from app.services.content_planning_service import ContentPlanningService
from app.services.scheduling_eligibility import check_scheduling_eligibility

router = APIRouter()


@router.get("/projects/{project_id}/generated-content/schedule/eligibility", response_model=PlanEligibilityResponse)
async def planning_eligibility(project_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Read-only: whether the project's saved post can be planned now, with the reasons when it cannot (the same
    rules the plan endpoint enforces). 404 for a project that is not yours. Writes nothing."""
    result = await check_scheduling_eligibility(db, user.id, project_id)
    if "project_not_found" in result.codes:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return {**result.as_dict(), "reasons": [r.__dict__ for r in result.reasons]}


@router.post("/projects/{project_id}/generated-content/schedule", response_model=ScheduleResponse,
             status_code=status.HTTP_201_CREATED)
async def plan_generated_content(project_id: UUID, body: PlanContentRequest, db: AsyncSession = Depends(get_db),
                                 user: User = Depends(get_current_user)):
    """Plan the project's approved, currently evaluated post (status "planned"). 404 for a project that is not
    yours, 409 with structured reasons when the post is not eligible, 422 for an invalid time or time zone."""
    return await ContentPlanningService(db, user.id).plan(
        project_id, scheduled_at=body.scheduled_at, zone_name=body.timezone, platform=body.platform,
        notes=body.notes, product_id=body.product_id)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleResponse)
async def reschedule_planned_entry(schedule_id: UUID, body: RescheduleRequest, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(get_current_user)):
    """Change time, time zone, platform or notes of a planned entry. Requires the current lock_version (409 if it
    changed); re-checks eligibility and that the planned post version is unchanged."""
    return await ContentPlanningService(db, user.id).reschedule(
        schedule_id, lock_version=body.lock_version, scheduled_at=body.scheduled_at, zone_name=body.timezone,
        platform=body.platform, notes=body.notes, notes_set="notes" in body.model_fields_set)


@router.post("/schedules/{schedule_id}/cancel", response_model=ScheduleResponse)
async def cancel_planned_entry(schedule_id: UUID, body: Optional[CancelPlanRequest] = Body(None),
                               db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Cancel a planned entry. The entry is kept (status "cancelled", cancelled_at); it is never deleted."""
    return await ContentPlanningService(db, user.id).cancel(schedule_id, lock_version=body.lock_version if body else None)
