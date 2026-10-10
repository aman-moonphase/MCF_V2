from typing import List, Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, ConfigDict, Field

class ScheduleBase(BaseModel):
    platform: str
    scheduled_at: datetime
    status: Optional[str] = Field("Scheduled", description="Status of the schedule")

class ScheduleCreate(ScheduleBase):
    project_id: UUID

class ScheduleUpdate(BaseModel):
    platform: Optional[str] = None
    scheduled_at: Optional[datetime] = None
    status: Optional[str] = None

class ScheduleResponse(ScheduleBase):
    id: UUID
    project_id: UUID
    created_at: datetime
    updated_at: datetime
    # Content planning (None for legacy entries, which were created before planning existed)
    product_id: Optional[UUID] = None
    generated_content_id: Optional[UUID] = None
    content_version: Optional[int] = None
    content_digest: Optional[str] = None
    content_type: Optional[str] = None
    timezone: Optional[str] = None
    notes: Optional[str] = None
    lock_version: int = 1
    cancelled_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ScheduleWithProjectResponse(ScheduleResponse):
    project_title: str

    class Config:
        from_attributes = True


# ─── Content planning (approved posts only; planning, never publishing) ─────

class PlanContentRequest(BaseModel):
    """Plan the project's approved, evaluated post. The status is always "planned" (not accepted from clients)."""
    model_config = ConfigDict(extra="forbid")

    scheduled_at: datetime = Field(description="Timezone-aware instant, e.g. 2026-11-03T09:00:00+05:30")
    timezone: str = Field(min_length=1, max_length=64, description="IANA zone the time was chosen in, e.g. Asia/Kolkata")
    platform: str = Field(min_length=1, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)
    product_id: Optional[UUID] = Field(None, description="Expected product; refused if the project belongs to another")


class RescheduleRequest(BaseModel):
    """Change only planning fields of a planned entry. `lock_version` must be the entry's current value."""
    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(ge=1)
    scheduled_at: Optional[datetime] = None
    timezone: Optional[str] = Field(None, min_length=1, max_length=64)
    platform: Optional[str] = Field(None, min_length=1, max_length=100)
    notes: Optional[str] = Field(None, max_length=2000)


class CancelPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lock_version: Optional[int] = Field(None, ge=1, description="When given, refused if the entry changed meanwhile")


# ─── Calendar listing (read-only) ───────────────────────────────────────────

class CalendarEntry(BaseModel):
    """One calendar entry. `status` is what is stored; `conditions` are derived for display only
    (date_passed, post_missing, post_changed, product_mismatch). Nothing here means published."""
    id: UUID
    project_id: UUID
    project_title: str
    product_id: Optional[UUID] = None
    product_name: Optional[str] = None
    scheduled_at: datetime
    scheduled_at_local: Optional[datetime] = None  # in the requested `timezone`, when one was given
    timezone: Optional[str] = None  # the IANA zone the entry was planned in (None for legacy entries)
    platform: str
    notes: Optional[str] = None
    status: str
    is_legacy: bool  # created before content planning: no post reference
    content_type: Optional[str] = None
    generated_content_id: Optional[UUID] = None
    content_version: Optional[int] = None
    content_digest: Optional[str] = None
    current_content_status: Optional[str] = None  # the linked post now, if it still exists in the project
    current_content_version: Optional[int] = None
    lock_version: int = 1
    cancelled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    conditions: List[str] = Field(default_factory=list)


class CalendarResponse(BaseModel):
    start: datetime
    end: datetime
    timezone: Optional[str] = None
    product_id: Optional[UUID] = None
    include_cancelled: bool = False
    entries: List[CalendarEntry]


class PlanningRefusal(BaseModel):
    code: str
    message: str


class PlanEligibilityResponse(BaseModel):
    """Read-only: may the project's saved post be planned now? (app/services/scheduling_eligibility.py)"""
    eligible: bool
    reasons: List[PlanningRefusal] = Field(default_factory=list)
    project_id: Optional[UUID] = None
    product_id: Optional[UUID] = None
    generated_content_id: Optional[UUID] = None
    content_type: Optional[str] = None
    platform: Optional[str] = None
    content_version: Optional[int] = None
    evaluation_id: Optional[UUID] = None
