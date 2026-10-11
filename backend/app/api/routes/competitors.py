from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.uploads import read_upload_limited
from app.db.session import get_db
from app.models.competitor import Competitor
from app.models.product import Product
from app.models.user import User
from app.schemas.competitor import (
    ApproveCompetitorAnalysisRequest, CompetitorAnalysisResponse, CompetitorCreate, CompetitorResponse,
    CompetitorUpdate, DiscoverResponse, EvidenceResponse,
)
from app.services.competitor_service import CompetitorService

# Mounted at /api/products
router = APIRouter()

_SUMMARY_FIELDS = ("name", "description", "category", "target_audience", "value_proposition", "key_features", "differentiators")


async def _competitor_response(service: CompetitorService, c: Competitor) -> CompetitorResponse:
    evidence = await service.evidence_for(c)
    has_evidence = any(e.status == "completed" for e in evidence)
    verification = (
        "evidence_backed" if has_evidence
        else "unverified" if c.origin == "ai_suggested"
        else "named_in_sources" if c.origin == "product_sources"
        else "user_added"
    )
    return CompetitorResponse(
        id=c.id, name=c.name, website_url=c.website_url, description=c.description, notes=c.notes,
        origin=c.origin, suggestion_reason=c.suggestion_reason, verification=verification,
        analysis_status=c.analysis_status, analysis=c.analysis, analysis_error=c.analysis_error,
        last_analyzed_at=c.last_analyzed_at,
        evidence=[
            EvidenceResponse(
                id=e.id, evidence_type=e.evidence_type, source_url=e.source_url, title=e.title, status=e.status,
                error=e.error, excerpt=(e.content or "")[:300] or None, char_count=len(e.content or ""), created_at=e.created_at,
            )
            for e in evidence
        ],
    )


async def _state(service: CompetitorService, product: Product) -> CompetitorAnalysisResponse:
    approved_profile = service.profile_is_approved(product)
    competitors = await service.competitors(product)
    version = product.competitor_version or 0
    comparison_current = product.competitor_comparison is not None and product.competitor_comparison_version == version
    if not approved_profile:
        state = "locked"
    elif product.competitor_approved_version == version and product.competitor_analysis_status == "approved":
        state = "approved"
    elif comparison_current:
        state = "ready_for_review"
    elif competitors:
        state = "in_progress"
    else:
        state = "not_started"
    profile = product.profile or {}
    return CompetitorAnalysisResponse(
        product_id=product.id, product_name=product.name, product_profile_approved=approved_profile,
        product_summary={k: profile.get(k) for k in _SUMMARY_FIELDS},
        status=state, version=version,
        approved_version=product.competitor_approved_version, approved_at=product.competitor_approved_at,
        limited_evidence=bool(product.competitor_limited_evidence) and state == "approved",
        comparison=product.competitor_comparison,
        comparison_outdated=product.competitor_comparison is not None and not comparison_current,
        comparison_at=product.competitor_comparison_at,
        competitors=[await _competitor_response(service, c) for c in competitors],
    )


@router.get("/{product_id}/competitor-analysis", response_model=CompetitorAnalysisResponse)
async def get_competitor_analysis(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    return await _state(service, await service.get_product(product_id))


@router.post("/{product_id}/competitors", response_model=CompetitorResponse, status_code=status.HTTP_201_CREATED)
async def create_competitor(product_id: UUID, body: CompetitorCreate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    return await _competitor_response(service, await service.create_competitor(product_id, body.model_dump()))


@router.patch("/{product_id}/competitors/{competitor_id}", response_model=CompetitorResponse)
async def update_competitor(product_id: UUID, competitor_id: UUID, body: CompetitorUpdate, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    changes = body.model_dump(exclude_unset=True)
    return await _competitor_response(service, await service.update_competitor(product_id, competitor_id, changes))


@router.delete("/{product_id}/competitors/{competitor_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competitor(product_id: UUID, competitor_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await CompetitorService(db, user.id).delete_competitor(product_id, competitor_id)


@router.post("/{product_id}/competitors/discover", response_model=DiscoverResponse)
async def discover_competitors(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    result = await service.discover(product_id)
    return DiscoverResponse(**result, state=await _state(service, await service.get_product(product_id)))


@router.post("/{product_id}/competitors/{competitor_id}/evidence", response_model=EvidenceResponse, status_code=status.HTTP_201_CREATED)
async def add_evidence(
    product_id: UUID,
    competitor_id: UUID,
    evidence_type: str = Form(...),
    content: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add evidence: a public URL (fetched safely), pasted observations, or a PDF."""
    service = CompetitorService(db, user.id)
    file_bytes = await read_upload_limited(file, settings.MAX_UPLOAD_BYTES) if file else None  # 413 when too large
    e = await service.add_evidence(product_id, competitor_id, evidence_type, content, title, file_bytes, file.filename if file else None)
    return EvidenceResponse(
        id=e.id, evidence_type=e.evidence_type, source_url=e.source_url, title=e.title, status=e.status, error=e.error,
        excerpt=(e.content or "")[:300] or None, char_count=len(e.content or ""), created_at=e.created_at,
    )


@router.delete("/{product_id}/competitors/{competitor_id}/evidence/{evidence_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_evidence(product_id: UUID, competitor_id: UUID, evidence_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    await CompetitorService(db, user.id).delete_evidence(product_id, competitor_id, evidence_id)


@router.post("/{product_id}/competitors/{competitor_id}/analyze", response_model=CompetitorResponse)
async def analyze_competitor(product_id: UUID, competitor_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    return await _competitor_response(service, await service.analyze(product_id, competitor_id))


@router.post("/{product_id}/competitor-comparison", response_model=CompetitorAnalysisResponse)
async def compare_competitors(product_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    return await _state(service, await service.compare(product_id))


@router.post("/{product_id}/competitor-analysis/approve", response_model=CompetitorAnalysisResponse)
async def approve_competitor_analysis(product_id: UUID, body: ApproveCompetitorAnalysisRequest, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    service = CompetitorService(db, user.id)
    return await _state(service, await service.approve(product_id, body.project_id, body.version, body.limited_evidence))
