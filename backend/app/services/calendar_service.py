"""Calendar listing: the user's calendar entries in a time range, with derived display conditions (read-only).

- Ownership and isolation are in the SQL: only entries of the user's own projects; product and post details are
  joined only when they belong to the same user (product) and the same project (post). Anything else is reported
  as a condition, never resolved through another user's data.
- `status` is the stored value ("planned", "cancelled", or a legacy value such as "Scheduled"). `conditions` are
  derived for display and never change the status — nothing here means published:
    date_passed      the entry's time is in the past (not cancelled)
    post_missing     a planned entry's post no longer exists in its project
    post_changed     the post's current version or content differs from the planned version/digest
    product_mismatch the entry's product differs from its project's product (or is not the user's)
- No full post text, claims or evidence is returned.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.generated_content import GeneratedContent
from app.models.product import Product
from app.models.project import Project
from app.models.schedule import Schedule
from app.services.content_planning_service import CANCELLED, _valid_zone, is_legacy
from app.services.scheduling_eligibility import content_digest

MAX_RANGE = timedelta(days=366)


@dataclass
class CalendarRange:
    start: datetime
    end: datetime
    zone: Optional[str]


def validate_range(start: datetime, end: datetime, zone: Optional[str]) -> CalendarRange:
    """[start, end) with explicit offsets, at most MAX_RANGE long; optional IANA zone for local display times."""
    problems = []
    for name, value in (("start", start), ("end", end)):
        if value.tzinfo is None or value.utcoffset() is None:
            problems.append(f"'{name}' must include a UTC offset (for example 2026-11-01T00:00:00+05:30).")
    if zone is not None and not _valid_zone(zone):
        problems.append("'timezone' must be a valid IANA time zone (for example Asia/Kolkata).")
    if not problems:
        if start >= end:
            problems.append("'start' must be before 'end'.")
        elif end - start > MAX_RANGE:
            problems.append("The range can be at most 366 days.")
    if problems:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=" ".join(problems))
    return CalendarRange(start, end, zone)


class CalendarService:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id

    async def entries(self, rng: CalendarRange, *, product_id: Optional[UUID] = None, include_cancelled: bool = False,
                      now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        if product_id is not None:
            owned = (await self.db.execute(select(Product.id).where(Product.id == product_id,
                                                                    Product.user_id == self.user_id))).scalar_one_or_none()
            if owned is None:  # someone else's product looks exactly like a missing one
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

        # The entry's product: the planned product, or (legacy) the project's product. Only the user's own products
        # are joined, so another user's product name can never appear.
        effective_product = func.coalesce(Schedule.product_id, Project.product_id)
        stmt = (
            select(Schedule, Project.title, Project.product_id, Product.id, Product.name,
                   GeneratedContent.status, GeneratedContent.version, GeneratedContent.content)
            .join(Project, Project.id == Schedule.project_id)
            .outerjoin(Product, and_(Product.id == effective_product, Product.user_id == self.user_id))
            .outerjoin(GeneratedContent, and_(GeneratedContent.id == Schedule.generated_content_id,
                                              GeneratedContent.project_id == Schedule.project_id))
            .where(Project.user_id == self.user_id, Schedule.scheduled_at >= rng.start, Schedule.scheduled_at < rng.end)
            .order_by(Schedule.scheduled_at.asc(), Schedule.created_at.asc().nulls_last(), Schedule.id.asc())
            .execution_options(populate_existing=True)  # always the stored values, never a cached instance
        )
        if not include_cancelled:
            stmt = stmt.where(Schedule.cancelled_at.is_(None), Schedule.status != CANCELLED)
        if product_id is not None:
            stmt = stmt.where(effective_product == product_id)

        zone = ZoneInfo(rng.zone) if rng.zone else None
        out = []
        for entry, project_title, project_product, product_id_, product_name, post_status, post_version, post_content \
                in (await self.db.execute(stmt)).all():
            legacy = is_legacy(entry)
            cancelled = entry.cancelled_at is not None or entry.status == CANCELLED
            conditions: List[str] = []
            if not cancelled and entry.scheduled_at < now:
                conditions.append("date_passed")
            post_exists = post_status is not None
            if not legacy:
                if not post_exists:
                    conditions.append("post_missing")
                elif post_version != entry.content_version or content_digest(post_content) != entry.content_digest:
                    conditions.append("post_changed")
                if entry.product_id is not None and (entry.product_id != project_product or product_id_ is None):
                    conditions.append("product_mismatch")
            out.append({
                "id": entry.id, "project_id": entry.project_id, "project_title": project_title,
                # Only the user's own product, and only when it is the entry's product.
                "product_id": product_id_, "product_name": product_name if product_id_ else None,
                "scheduled_at": entry.scheduled_at,
                "scheduled_at_local": entry.scheduled_at.astimezone(zone) if zone else None,
                "timezone": entry.timezone, "platform": entry.platform, "notes": entry.notes, "status": entry.status,
                "is_legacy": legacy, "content_type": entry.content_type,
                "generated_content_id": entry.generated_content_id if not legacy else None,
                "content_version": entry.content_version, "content_digest": entry.content_digest,
                "current_content_status": post_status if post_exists else None,
                "current_content_version": post_version if post_exists else None,
                "lock_version": entry.lock_version, "cancelled_at": entry.cancelled_at,
                "created_at": entry.created_at, "updated_at": entry.updated_at, "conditions": conditions,
            })
        return out
