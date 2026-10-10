import uuid
from datetime import datetime
from typing import List, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import desc

from app.db.session import get_db
from app.models.schedule import Schedule
from app.models.project import Project
from app.models.workflow_stage import WorkflowStage
from app.schemas.schedule import CalendarResponse, ScheduleCreate, ScheduleUpdate, ScheduleResponse, ScheduleWithProjectResponse
from app.api.deps import get_current_user
from app.models.user import User
from app.services.project_service import ProjectService
from app.services.content_planning_service import LEGACY_STATUS, is_legacy
from app.services.calendar_service import CalendarService, validate_range

router = APIRouter()

# Legacy routes (entries created before content planning). Approved posts are planned, rescheduled and cancelled
# through app/api/routes/content_planning.py. These routes can never set a planning or publishing status, and never
# change or delete a planned entry.
LEGACY_STATUSES = frozenset({LEGACY_STATUS})


def _legacy_status(requested, current=None):
    """Legacy entries keep "Scheduled" (or their existing value). Anything else — "Published", "Completed",
    "planned", "cancelled", ... — is refused: status changes are not a way around eligibility or cancellation."""
    if requested is None or requested in LEGACY_STATUSES or (current is not None and requested == current):
        return
    raise HTTPException(status_code=422, detail=f"Status '{requested}' cannot be set here. Legacy entries keep the status "
                                                 f"'{LEGACY_STATUS}'; approved posts are planned through Content Planning.")


def _require_aware(value):
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise HTTPException(status_code=422, detail="The scheduled time must include a time zone offset.")


def _refuse_planned(schedule: Schedule, action: str):
    if not is_legacy(schedule):
        raise HTTPException(status_code=409, detail=f"This entry plans an approved post and cannot be {action} here. "
                                                    "Use the reschedule or cancel actions instead.")

@router.post("", response_model=ScheduleResponse)
async def create_schedule(schedule_in: ScheduleCreate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # Verify project exists and belongs to user
    project_service = ProjectService(db, current_user.id)
    project = await project_service.get_project(schedule_in.project_id)
    _legacy_status(schedule_in.status)
    _require_aware(schedule_in.scheduled_at)

    # Verify project has approved content (at least Script stage)
    stmt = select(WorkflowStage).where(
        WorkflowStage.project_id == schedule_in.project_id,
        WorkflowStage.stage_type.in_(["script", "final-script"]),
        WorkflowStage.status.in_(["completed", "Completed"])
    )
    result = await db.execute(stmt)
    script_stage = result.scalars().first()  # a project may have both a script and a final-script stage

    if not script_stage:
        raise HTTPException(
            status_code=400, 
            detail="Cannot schedule project: No completed script found. Human approval of script is required."
        )

    db_schedule = Schedule(
        project_id=schedule_in.project_id,
        platform=schedule_in.platform,
        scheduled_at=schedule_in.scheduled_at,
        status=LEGACY_STATUS
    )
    db.add(db_schedule)
    await db.commit()
    await db.refresh(db_schedule)
    return db_schedule

@router.get("", response_model=List[ScheduleWithProjectResponse])
async def list_schedules(include_cancelled: bool = False, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    stmt = select(Schedule, Project.title.label("project_title")).join(Project, Schedule.project_id == Project.id).where(Project.user_id == current_user.id).order_by(Schedule.scheduled_at.asc())
    if not include_cancelled:  # cancelled plans are kept for history but are not on the calendar
        stmt = stmt.where(Schedule.cancelled_at.is_(None))
    result = await db.execute(stmt)
    
    schedules = []
    for sched, proj_title in result.all():
        sched_dict = sched.__dict__.copy()
        sched_dict["project_title"] = proj_title
        schedules.append(sched_dict)
        
    return schedules

@router.get("/calendar", response_model=CalendarResponse)
async def calendar_entries(
    start: datetime = Query(..., description="Range start, inclusive, with UTC offset (encode '+' as %2B)"),
    end: datetime = Query(..., description="Range end, exclusive, with UTC offset"),
    product_id: Optional[uuid.UUID] = None,
    include_cancelled: bool = False,
    timezone: Optional[str] = Query(None, description="IANA zone for scheduled_at_local, e.g. Asia/Kolkata"),
    db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user),
):
    """The user's calendar entries with scheduled_at in [start, end), oldest first. Read-only."""
    rng = validate_range(start, end, timezone)
    entries = await CalendarService(db, current_user.id).entries(rng, product_id=product_id, include_cancelled=include_cancelled)
    return {"start": start, "end": end, "timezone": timezone, "product_id": product_id,
            "include_cancelled": include_cancelled, "entries": entries}


async def get_schedule_with_ownership_check(schedule_id: uuid.UUID, db: AsyncSession, current_user: User) -> Schedule:
    stmt = select(Schedule).join(Project).where(Schedule.id == schedule_id, Project.user_id == current_user.id)
    result = await db.execute(stmt)
    schedule = result.scalar_one_or_none()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule

@router.get("/{schedule_id}", response_model=ScheduleResponse)
async def get_schedule(schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    return await get_schedule_with_ownership_check(schedule_id, db, current_user)

@router.put("/{schedule_id}", response_model=ScheduleResponse)
async def update_schedule(schedule_id: uuid.UUID, schedule_in: ScheduleUpdate, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_schedule = await get_schedule_with_ownership_check(schedule_id, db, current_user)
    _refuse_planned(db_schedule, "edited")
    _legacy_status(schedule_in.status, current=db_schedule.status)
    _require_aware(schedule_in.scheduled_at)

    update_data = schedule_in.model_dump(exclude_unset=True)
    if update_data.get("status") is None:
        update_data.pop("status", None)
    for field, value in update_data.items():
        setattr(db_schedule, field, value)
    db_schedule.lock_version = (db_schedule.lock_version or 1) + 1

    await db.commit()
    await db.refresh(db_schedule)
    return db_schedule

@router.delete("/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    db_schedule = await get_schedule_with_ownership_check(schedule_id, db, current_user)
    _refuse_planned(db_schedule, "deleted")  # planned entries are cancelled (kept), never deleted

    await db.delete(db_schedule)
    await db.commit()
