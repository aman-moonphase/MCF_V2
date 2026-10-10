"""Calendar & content planning: create, reschedule and cancel PLANNED calendar entries for approved posts.

Planning is not publishing. A planned entry records that a human intends to post an approved, evaluated version of
a post at a time; nothing here posts, sends or schedules work anywhere, and no entry is ever marked published.

- Eligibility comes only from `check_scheduling_eligibility` (approval, current context, current evaluation, ...).
- A planned entry pins the post: generated-content id, exact version and content digest. Rescheduling re-checks
  eligibility AND that the post is still exactly what was planned.
- Times: the client sends a timezone-aware instant plus the IANA zone it was chosen in. The instant's UTC offset
  must be the zone's offset at that instant, so a wall-clock time that does not exist (DST gap) or the wrong side
  of a DST overlap is rejected instead of silently shifted. The server's own clock zone is never used.
- Concurrency: every change requires the entry's current `lock_version` and is applied with a conditional UPDATE
  (… WHERE lock_version = :expected), so concurrent edits cannot overwrite each other.
- Entries are never deleted here: cancelling keeps the row (status "cancelled", cancelled_at).
- Legacy entries (created before planning; no post reference) keep their data and their old routes.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.platform_policy import MVP_PLATFORM_KEY, platform_policy
from app.models.project import Project
from app.models.schedule import Schedule
from app.services.scheduling_eligibility import Refusal, SchedulingEligibility, check_scheduling_eligibility

PLANNED, CANCELLED = "planned", "cancelled"
PLANNING_STATUSES = (PLANNED, CANCELLED)
LEGACY_STATUS = "Scheduled"
DUPLICATE_INDEX = "uq_schedules_active_plan"
# Refusals about the request itself — time, time zone, platform (422); every other refusal is a state conflict (409).
REQUEST_CODES = frozenset({"timezone_required", "invalid_timezone", "timezone_mismatch", "time_in_past", "unsupported_platform"})


def is_legacy(entry: Schedule) -> bool:
    """Created before content planning: no post reference was ever recorded (a planned entry keeps its version even
    if its post is later deleted)."""
    return entry.generated_content_id is None and entry.content_version is None


def _error(code: int, message: str, reasons: List[Refusal], **extra) -> HTTPException:
    return HTTPException(status_code=code, detail={"message": message, "reasons": [r.__dict__ for r in reasons], **extra})


def _valid_zone(name: Optional[str]) -> bool:
    """A real IANA zone name (from the tzdata package; never the server's local zone)."""
    if not name or name != name.strip() or len(name) > 64:
        return False
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def time_problems(scheduled_at: Optional[datetime], zone_name: Optional[str]) -> List[Refusal]:
    """The requested instant must carry an explicit offset and a valid IANA zone, and the offset must be the one that
    zone uses at that instant (rejects DST-gap times and the wrong side of a DST overlap)."""
    problems: List[Refusal] = []
    zone = ZoneInfo(zone_name) if _valid_zone(zone_name) else None
    if zone is None:
        problems.append(Refusal("invalid_timezone", "Choose a valid IANA time zone (for example Asia/Kolkata)."))
    if scheduled_at is None or scheduled_at.tzinfo is None or scheduled_at.utcoffset() is None:
        problems.append(Refusal("timezone_required", "The planned time must include its UTC offset."))
    elif zone is not None and scheduled_at.astimezone(zone).utcoffset() != scheduled_at.utcoffset():
        local = scheduled_at.astimezone(zone)
        problems.append(Refusal(
            "timezone_mismatch",
            f"That time does not exist as given in {zone_name}: at that moment {zone_name} is at UTC"
            f"{local.strftime('%z')[:3]}:{local.strftime('%z')[3:]}, not UTC{scheduled_at.strftime('%z')[:3]}:"
            f"{scheduled_at.strftime('%z')[3:]} (this can happen around daylight-saving changes). Choose the time again."))
    return problems


def _platform(value: str) -> Optional[str]:
    """Canonical stored platform name for a supported platform, else None (MVP: LinkedIn only)."""
    policy = platform_policy(MVP_PLATFORM_KEY)
    return policy.name if (value or "").strip().lower() in (policy.key, policy.name.lower()) else None


def _raise_for(result: SchedulingEligibility, extra: List[Refusal]) -> None:
    reasons = [*result.reasons, *extra]
    if not reasons:
        return
    if "project_not_found" in [r.code for r in reasons]:
        raise _error(status.HTTP_404_NOT_FOUND, "Project not found.", [Refusal("project_not_found", "Project not found.")])
    if all(r.code in REQUEST_CODES for r in reasons):
        raise _error(status.HTTP_422_UNPROCESSABLE_ENTITY, "The planned time or platform is not valid.", reasons)
    raise _error(status.HTTP_409_CONFLICT, "This post cannot be planned.", reasons)


def _duplicate(exc: IntegrityError) -> bool:
    return DUPLICATE_INDEX in str(getattr(exc, "orig", exc))


DUPLICATE_REFUSAL = Refusal("duplicate_plan", "This version of the post is already planned on this platform at this time.")


class ContentPlanningService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id

    async def _owned_entry(self, schedule_id: UUID) -> Schedule:
        entry = (await self.db.execute(select(Schedule).join(Project, Project.id == Schedule.project_id)
                                       .where(Schedule.id == schedule_id, Project.user_id == self.user_id)
                                       .execution_options(populate_existing=True))).scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=404, detail="Schedule not found")
        return entry

    async def plan(self, project_id: UUID, *, scheduled_at: datetime, zone_name: str, platform: str,
                   notes: Optional[str] = None, product_id: Optional[UUID] = None) -> Schedule:
        result = await check_scheduling_eligibility(self.db, self.user_id, project_id, product_id=product_id,
                                                    scheduled_at=scheduled_at)
        extra = [] if "project_not_found" in result.codes else time_problems(scheduled_at, zone_name)
        canonical = _platform(platform)
        if canonical is None or (result.platform and canonical.lower() != result.platform):  # e.g. "linkedin"
            extra.append(Refusal("unsupported_platform", "Only LinkedIn can be planned for this post in this version."))
        # Avoid reporting the same time problem twice (eligibility also checks for a missing offset).
        extra = [r for r in extra if r.code not in result.codes]
        _raise_for(result, extra)

        entry = Schedule(project_id=result.project_id, product_id=result.product_id,
                         generated_content_id=result.generated_content_id, content_version=result.content_version,
                         content_digest=result.content_digest, content_type=result.content_type, platform=canonical,
                         scheduled_at=scheduled_at, timezone=zone_name, notes=notes, status=PLANNED, lock_version=1)
        self.db.add(entry)
        try:
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if _duplicate(exc):
                raise _error(status.HTTP_409_CONFLICT, "This post cannot be planned.", [DUPLICATE_REFUSAL])
            raise
        await self.db.refresh(entry)
        return entry

    def _require_planned(self, entry: Schedule, action: str) -> None:
        if is_legacy(entry):
            raise _error(status.HTTP_409_CONFLICT, f"Entries created before content planning cannot be {action} here.",
                         [Refusal("legacy_entry", "This is a legacy calendar entry without a planned post version.")])
        if entry.status == CANCELLED or entry.cancelled_at is not None:
            raise _error(status.HTTP_409_CONFLICT, f"A cancelled entry cannot be {action}.",
                         [Refusal("cancelled", "This entry is cancelled. Plan the post again instead.")])

    def _lock_conflict(self, current: int) -> HTTPException:
        return _error(status.HTTP_409_CONFLICT, "This entry was changed by someone else. Reload it and try again.",
                      [Refusal("lock_conflict", "The entry's lock_version no longer matches.")], lock_version=current)

    async def _apply(self, entry: Schedule, expected: int, values: Dict[str, Any]) -> Schedule:
        """Conditional update: only applies if nobody changed the entry since `expected`."""
        entry_id = entry.id  # read before any rollback expires the instance
        try:
            done = await self.db.execute(
                update(Schedule).where(Schedule.id == entry_id, Schedule.lock_version == expected)
                .values(**values, lock_version=Schedule.lock_version + 1, updated_at=datetime.now(timezone.utc))
                .execution_options(synchronize_session=False))
            if done.rowcount != 1:
                await self.db.rollback()
                current = (await self.db.execute(select(Schedule.lock_version).where(Schedule.id == entry_id))).scalar()
                raise self._lock_conflict(current)
            await self.db.commit()
        except IntegrityError as exc:
            await self.db.rollback()
            if _duplicate(exc):
                raise _error(status.HTTP_409_CONFLICT, "This entry cannot be moved there.", [DUPLICATE_REFUSAL])
            raise
        return await self._owned_entry(entry_id)

    async def reschedule(self, schedule_id: UUID, *, lock_version: int, scheduled_at: Optional[datetime] = None,
                         zone_name: Optional[str] = None, platform: Optional[str] = None,
                         notes: Optional[str] = None, notes_set: bool = False) -> Schedule:
        entry = await self._owned_entry(schedule_id)
        self._require_planned(entry, "rescheduled")
        if entry.lock_version != lock_version:
            raise self._lock_conflict(entry.lock_version)

        new_time = scheduled_at if scheduled_at is not None else entry.scheduled_at
        new_zone = zone_name if zone_name is not None else entry.timezone
        extra: List[Refusal] = []
        if scheduled_at is not None:
            extra += time_problems(scheduled_at, new_zone)
        elif zone_name is not None and not _valid_zone(zone_name):
            # Only the zone changes: the stored instant is kept and simply shown in the new zone.
            extra.append(Refusal("invalid_timezone", "Choose a valid IANA time zone (for example Asia/Kolkata)."))
        canonical = _platform(platform) if platform is not None else entry.platform
        if canonical is None:
            extra.append(Refusal("unsupported_platform", "Only LinkedIn can be planned for this post in this version."))

        result = await check_scheduling_eligibility(self.db, self.user_id, entry.project_id, product_id=entry.product_id,
                                                    scheduled_at=new_time)
        if result.generated_content_id is not None or entry.generated_content_id is None:
            # The post must still be exactly what was planned (same post, version and content).
            if (result.generated_content_id, result.content_version, result.content_digest) != (
                    entry.generated_content_id, entry.content_version, entry.content_digest):
                extra.append(Refusal("content_changed", "The post changed since it was planned. Cancel this entry and "
                                                        "plan the current approved version."))
        extra = [r for r in extra if r.code not in result.codes]
        _raise_for(result, extra)

        values: Dict[str, Any] = {"scheduled_at": new_time, "timezone": new_zone, "platform": canonical}
        if notes_set:
            values["notes"] = notes
        return await self._apply(entry, lock_version, values)

    async def cancel(self, schedule_id: UUID, *, lock_version: Optional[int] = None) -> Schedule:
        entry = await self._owned_entry(schedule_id)
        self._require_planned(entry, "cancelled")
        if lock_version is not None and entry.lock_version != lock_version:
            raise self._lock_conflict(entry.lock_version)
        return await self._apply(entry, entry.lock_version, {"status": CANCELLED, "cancelled_at": datetime.now(timezone.utc)})
