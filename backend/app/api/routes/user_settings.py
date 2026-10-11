"""The signed-in user's preferences (GET / PUT /api/settings/me). Only the caller's own row is read or written."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.models.user_settings import DEFAULT_CALENDAR_VIEW, DEFAULT_PLAN_TIME, UserSettings
from app.schemas.user_settings import UserSettingsResponse, UserSettingsUpdate

router = APIRouter()


def _response(row: UserSettings | None) -> UserSettingsResponse:
    if row is None:
        return UserSettingsResponse(timezone=None, calendar_default_view=DEFAULT_CALENDAR_VIEW,
                                    default_plan_time=DEFAULT_PLAN_TIME, saved=False, updated_at=None)
    return UserSettingsResponse(timezone=row.timezone, calendar_default_view=row.calendar_default_view,
                                default_plan_time=row.default_plan_time, saved=True, updated_at=row.updated_at)


async def _own_row(db: AsyncSession, user_id: int) -> UserSettings | None:
    return (await db.execute(select(UserSettings).where(UserSettings.user_id == user_id)
                             .execution_options(populate_existing=True))).scalar_one_or_none()


@router.get("/me", response_model=UserSettingsResponse)
async def get_my_settings(db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Your preferences (defaults when none are saved). Read-only."""
    return _response(await _own_row(db, user.id))


@router.put("/me", response_model=UserSettingsResponse)
async def save_my_settings(body: UserSettingsUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Save your preferences (validated: IANA zone or null, month/week/day, HH:MM). Returns what was stored."""
    row = await _own_row(db, user.id)
    if row is None:
        row = UserSettings(user_id=user.id)
        db.add(row)
    row.timezone = body.timezone
    row.calendar_default_view = body.calendar_default_view
    row.default_plan_time = body.default_plan_time
    await db.commit()
    return _response(await _own_row(db, user.id))
