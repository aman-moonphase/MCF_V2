"""Read-only version history of a project's generated post (mounted at /api/projects)."""
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.generated_content_version import GeneratedContentVersion
from app.models.user import User
from app.services.project_service import ProjectService

router = APIRouter()


class ContentVersionSummary(BaseModel):
    version: int
    status: str  # draft | approved
    edited: bool  # a person's hand edit (otherwise generated)
    provider: Optional[str] = None
    is_demo: bool = False
    generated_at: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    hook: Optional[str] = None


class ContentVersionDetail(ContentVersionSummary):
    content: Dict[str, Any]
    validation: Optional[Dict[str, Any]] = None
    context_snapshot: Optional[Dict[str, Any]] = None


def _summary(row: GeneratedContentVersion) -> Dict[str, Any]:
    return dict(version=row.version, status=row.status, edited=row.edited, provider=row.provider, is_demo=row.is_demo,
                generated_at=row.generated_at, edited_at=row.edited_at, approved_at=row.approved_at,
                hook=(row.content or {}).get("hook"))


@router.get("/{project_id}/generated-content/versions", response_model=List[ContentVersionSummary])
async def list_content_versions(project_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Every saved version of this project's post, newest first. 404 unless the project is yours."""
    project = await ProjectService(db, user.id).get_project(project_id)
    rows = (await db.execute(select(GeneratedContentVersion).where(GeneratedContentVersion.project_id == project.id)
                             .order_by(GeneratedContentVersion.version.desc()))).scalars().all()
    return [_summary(r) for r in rows]


@router.get("/{project_id}/generated-content/versions/{version}", response_model=ContentVersionDetail)
async def get_content_version(project_id: UUID, version: int, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """The full content of one saved post version (for example the text before a later edit or regeneration)."""
    project = await ProjectService(db, user.id).get_project(project_id)
    row = (await db.execute(select(GeneratedContentVersion).where(
        GeneratedContentVersion.project_id == project.id, GeneratedContentVersion.version == version))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="That post version does not exist.")
    return {**_summary(row), "content": row.content, "validation": row.validation, "context_snapshot": row.context_snapshot}
