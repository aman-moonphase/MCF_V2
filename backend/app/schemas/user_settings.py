from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

CalendarView = Literal["month", "week", "day"]
PLAN_TIME_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class UserSettingsResponse(BaseModel):
    """The caller's preferences. `saved` is False while the defaults are in use (nothing stored yet)."""
    timezone: Optional[str] = None  # IANA zone for new plans; None = the browser's zone
    calendar_default_view: CalendarView = "month"
    default_plan_time: str = "09:00"
    saved: bool = False
    updated_at: Optional[datetime] = None


class UserSettingsUpdate(BaseModel):
    """Replace the caller's preferences. Unknown fields are refused (no credentials or provider settings here)."""
    model_config = ConfigDict(extra="forbid")

    timezone: Optional[str] = Field(None, max_length=64, description="IANA zone, e.g. Asia/Kolkata; null = browser zone")
    calendar_default_view: CalendarView
    default_plan_time: str = Field(pattern=PLAN_TIME_PATTERN, description="HH:MM, 24-hour")

    @field_validator("timezone")
    @classmethod
    def _valid_zone(cls, value: Optional[str]) -> Optional[str]:
        from app.services.content_planning_service import _valid_zone

        if value is None or value == "":
            return None
        if not _valid_zone(value):
            raise ValueError("must be a valid IANA time zone, e.g. Asia/Kolkata")
        return value
