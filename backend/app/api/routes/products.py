from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.product import Product
from app.models.user import User
from app.schemas.product import (
    ApproveProfileRequest, LinkProductRequest, ProductResponse, SubmitAnswersRequest, UpdateProfileRequest,
)
from app.services.product_service import ProductService

# Product-level endpoints: /api/products/...
router = APIRouter()
# Project-scoped endpoints: /api/projects/{project_id}/product...
project_router = APIRouter()


async def _response(service: ProductService, product: Product) -> ProductResponse:
    return ProductResponse(
        id=product.id,
        name=product.name,
        description=product.description,
        understanding_status=product.understanding_status,
        profile=product.profile,
        clarification_questions=product.clarification_questions or [],
        edited_fields=product.edited_fields or [],
        profile_version=product.profile_version or 0,
        approved_version=product.approved_version,
        approved_at=product.approved_at,
        updated_at=product.updated_at,
        project_ids=await service.project_ids(product),
    )


@router.get("", response_model=List[ProductResponse])
async def list_products(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProductService(db, current_user.id)
    return [await _response(service, p) for p in await service.list_products()]


@router.get("/{product_id}", response_model=ProductResponse)
async def get_product(product_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProductService(db, current_user.id)
    return await _response(service, await service.get_product(product_id))


@router.patch("/{product_id}/profile", response_model=ProductResponse)
async def update_profile(product_id: UUID, body: UpdateProfileRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProductService(db, current_user.id)
    return await _response(service, await service.update_profile(product_id, body.profile))


@router.post("/{product_id}/clarifications", response_model=ProductResponse)
async def submit_clarifications(product_id: UUID, body: SubmitAnswersRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProductService(db, current_user.id)
    answers = [a.model_dump() for a in body.answers]
    return await _response(service, await service.submit_answers(product_id, body.project_id, answers))


@router.post("/{product_id}/approve", response_model=ProductResponse)
async def approve_profile(product_id: UUID, body: ApproveProfileRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    service = ProductService(db, current_user.id)
    return await _response(service, await service.approve(product_id, body.project_id, body.profile_version))


@project_router.post("/{project_id}/product-understanding", response_model=ProductResponse)
async def run_product_understanding(project_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Start, or refresh, Product Understanding from this project's sources."""
    service = ProductService(db, current_user.id)
    return await _response(service, await service.run_understanding(project_id))


@project_router.get("/{project_id}/product", response_model=Optional[ProductResponse])
async def get_project_product(project_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """The product linked to this project, or null when Product Understanding has not started."""
    service = ProductService(db, current_user.id)
    product = await service.get_project_product(project_id)
    return await _response(service, product) if product else None


@project_router.put("/{project_id}/product", response_model=ProductResponse)
async def link_project_product(project_id: UUID, body: LinkProductRequest, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Reuse an existing product (and its profile) for this project."""
    service = ProductService(db, current_user.id)
    return await _response(service, await service.link_project(project_id, body.product_id))


@project_router.get("/{project_id}/product/approved-profile")
async def get_approved_profile(project_id: UUID, db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Approved Product Profile for downstream stages; 409 until the profile is approved."""
    return await ProductService(db, current_user.id).get_approved_profile(project_id)
