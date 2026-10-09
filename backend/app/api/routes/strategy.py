from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.product import Product
from app.models.user import User
from app.services.strategy_service import StrategyService

# Mounted at /api/products
router = APIRouter()


class StrategyStateResponse(BaseModel):
    product_id: UUID
    product_name: str
    prerequisites_met: bool
    prerequisite_problem: Optional[str] = None
    limited_evidence: bool = False
    status: str  # not_generated | draft | approved
    strategy: Optional[Dict[str, Any]] = None
    version: Optional[int] = None
    approved_version: Optional[int] = None
    approved_at: Optional[datetime] = None
    stale: bool = False
    edited_sections: List[str] = []
    basis: Optional[Dict[str, Any]] = None
    provider: Optional[str] = None
    generated_at: Optional[datetime] = None


class UpdateStrategyRequest(BaseModel):
    strategy: Dict[str, Any]


class ApproveStrategyRequest(BaseModel):
    project_id: UUID
    version: int


async def _state(service: StrategyService, product: Product) -> StrategyStateResponse:
    strategy = await service.get_strategy(product)
    problem = service.prerequisite_problem(product)
    base = dict(
        product_id=product.id, product_name=product.name, prerequisites_met=problem is None,
        prerequisite_problem=problem, limited_evidence=bool(product.competitor_limited_evidence),
    )
    if not strategy:
        return StrategyStateResponse(**base, status="not_generated")
    approved = strategy.status == "approved" and strategy.approved_version == strategy.version
    return StrategyStateResponse(
        **base, status="approved" if approved else "draft", strategy=strategy.strategy, version=strategy.version,
        approved_version=strategy.approved_version, approved_at=strategy.approved_at,
        stale=service.is_stale(strategy, product), edited_sections=strategy.edited_sections or [],
        basis=strategy.basis, provider=strategy.provider, generated_at=strategy.generated_at,
    )


@router.get("/{product_id}/promotion-strategy", response_model=StrategyStateResponse)
async def get_strategy(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = StrategyService(db, user.id)
    return await _state(service, await service.products.get_product(product_id))


@router.post("/{product_id}/promotion-strategy", response_model=StrategyStateResponse)
async def generate_strategy(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = StrategyService(db, user.id)
    await service.generate(product_id)
    return await _state(service, await service.products.get_product(product_id))


@router.patch("/{product_id}/promotion-strategy", response_model=StrategyStateResponse)
async def update_strategy(product_id: UUID, body: UpdateStrategyRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = StrategyService(db, user.id)
    await service.update(product_id, body.strategy)
    return await _state(service, await service.products.get_product(product_id))


@router.post("/{product_id}/promotion-strategy/approve", response_model=StrategyStateResponse)
async def approve_strategy(product_id: UUID, body: ApproveStrategyRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = StrategyService(db, user.id)
    await service.approve(product_id, body.project_id, body.version)
    return await _state(service, await service.products.get_product(product_id))
