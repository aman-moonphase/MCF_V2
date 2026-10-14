"""Read-only version history of a product's promotion strategy (mounted at /api/products)."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.promotion_strategy_version import PromotionStrategyVersion
from app.models.user import User
from app.services.product_service import ProductService

router = APIRouter()


class StrategyVersionSummary(BaseModel):
    version: int
    status: str  # draft | approved
    approved_at: Optional[datetime] = None
    edited_sections: List[str] = []
    provider: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class StrategyVersionDetail(StrategyVersionSummary):
    strategy: Dict[str, Any]
    basis: Optional[Dict[str, Any]] = None


def _summary(row: PromotionStrategyVersion) -> Dict[str, Any]:
    return dict(version=row.version, status=row.status, approved_at=row.approved_at, edited_sections=row.edited_sections or [],
                provider=row.provider, created_at=row.created_at, updated_at=row.updated_at)


@router.get("/{product_id}/strategy/versions", response_model=List[StrategyVersionSummary])
async def list_strategy_versions(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Every saved version of this product's strategy, newest first. 404 unless the product is yours."""
    await ProductService(db, user.id).get_product(product_id)
    rows = (await db.execute(select(PromotionStrategyVersion).where(PromotionStrategyVersion.product_id == product_id)
                             .order_by(PromotionStrategyVersion.version.desc()))).scalars().all()
    return [_summary(r) for r in rows]


@router.get("/{product_id}/strategy/versions/{version}", response_model=StrategyVersionDetail)
async def get_strategy_version(product_id: UUID, version: int, db: AsyncSession = Depends(get_db),
                               user: User = Depends(get_current_user)):
    """The full content of one saved strategy version (for example the approved one after a later edit)."""
    await ProductService(db, user.id).get_product(product_id)
    row = (await db.execute(select(PromotionStrategyVersion).where(
        PromotionStrategyVersion.product_id == product_id, PromotionStrategyVersion.version == version))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="That strategy version does not exist.")
    return {**_summary(row), "strategy": row.strategy, "basis": row.basis}
