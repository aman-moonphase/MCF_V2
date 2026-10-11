from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Integer, String

from app.db.base_class import Base

CALENDAR_VIEWS = ("month", "week", "day")
DEFAULT_CALENDAR_VIEW = "month"
DEFAULT_PLAN_TIME = "09:00"


class UserSettings(Base):
    """Per-user preferences (one row per user; absent row = defaults). Only preferences for behaviour that already
    exists: the calendar's opening view and the defaults of the Add to Calendar dialog. No credentials or provider
    configuration live here — those stay server-side in the environment. Schema: alembic a0b1c2d3e4f5."""

    __tablename__ = "user_settings"
    __table_args__ = (
        CheckConstraint("calendar_default_view IN ('month', 'week', 'day')", name="ck_user_settings_calendar_view"),
        CheckConstraint("default_plan_time ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$'", name="ck_user_settings_plan_time"),
    )

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    # IANA zone for new plans; NULL = use the browser's zone.
    timezone = Column(String(64), nullable=True)
    calendar_default_view = Column(String(10), nullable=False, default=DEFAULT_CALENDAR_VIEW, server_default=DEFAULT_CALENDAR_VIEW)
    default_plan_time = Column(String(5), nullable=False, default=DEFAULT_PLAN_TIME, server_default=DEFAULT_PLAN_TIME)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
