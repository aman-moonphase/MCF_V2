from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.generation_service import MAX_INSTRUCTIONS_CHARS, GenerationService

# Mounted at /api/projects
router = APIRouter()


class Prerequisite(BaseModel):
    key: str
    label: str
    met: bool
    detail: Optional[str] = None


class GeneratedDraft(BaseModel):
    id: UUID
    content: Dict[str, Any]
    validation: Optional[Dict[str, Any]] = None
    status: str
    version: int
    edited: bool
    provider: Optional[str] = None
    is_demo: bool
    generated_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    approved_version: Optional[int] = None
    approved_at: Optional[datetime] = None
    usage: Optional[Dict[str, Any]] = None  # API usage + estimated cost of the generating request(s); None in Demo Mode
    context_snapshot: Optional[Dict[str, Any]] = None
    evidence: List[Dict[str, str]] = []


class GenerationStateResponse(BaseModel):
    project_id: UUID
    # not_applicable (legacy project) | blocked | not_generated | draft | approved
    status: str
    can_generate: bool
    blocking_problem: Optional[str] = None
    prerequisites: List[Prerequisite] = []
    context: Optional[Dict[str, Any]] = None
    draft: Optional[GeneratedDraft] = None
    stale: bool = False
    stale_reasons: List[str] = []
    policy: Dict[str, Any]
    provider: str


class GenerateRequest(BaseModel):
    # Only choices are accepted from the client; all context is loaded server-side.
    pillar_index: int = 0
    instructions: Optional[str] = Field(default=None, max_length=MAX_INSTRUCTIONS_CHARS)


class ApprovePostRequest(BaseModel):
    # The version the reviewer saw; approval is refused if the saved post changed since.
    version: int


class UpdatePostRequest(BaseModel):
    hook: Optional[str] = None
    alternative_hooks: Optional[List[str]] = None
    body: Optional[str] = None
    cta: Optional[str] = None
    hashtags: Optional[List[str]] = None
    version: Optional[int] = None


@router.get("/{project_id}/generated-content", response_model=GenerationStateResponse)
async def get_generated_content(project_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    return await GenerationService(db, user.id).state(project_id)


@router.post("/{project_id}/generated-content", response_model=GenerationStateResponse)
async def generate_content(project_id: UUID, body: GenerateRequest, db: AsyncSession = Depends(get_db),
                           user: User = Depends(get_current_user)):
    service = GenerationService(db, user.id)
    await service.generate(project_id, body.pillar_index, body.instructions)
    return await service.state(project_id)


@router.patch("/{project_id}/generated-content", response_model=GenerationStateResponse)
async def update_generated_content(project_id: UUID, body: UpdatePostRequest, db: AsyncSession = Depends(get_db),
                                   user: User = Depends(get_current_user)):
    service = GenerationService(db, user.id)
    changes = body.model_dump(exclude_unset=True, exclude={"version"})
    await service.update(project_id, changes, body.version)
    return await service.state(project_id)


@router.post("/{project_id}/generated-content/approve", response_model=GenerationStateResponse)
async def approve_generated_content(project_id: UUID, body: ApprovePostRequest, db: AsyncSession = Depends(get_db),
                                    user: User = Depends(get_current_user)):
    """Human approval of the saved post. Records the decision only — never publishes, schedules or sends it."""
    service = GenerationService(db, user.id)
    await service.approve(project_id, body.version)
    return await service.state(project_id)
