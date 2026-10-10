from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.services.evaluation_service import EvaluationService

# Mounted at /api/projects
router = APIRouter()


class EvaluateRequest(BaseModel):
    # The version the user is looking at; evaluation is refused if the saved post changed since.
    version: int


@router.get("/{project_id}/evaluation", response_model=Dict[str, Any])
async def get_evaluation(project_id: UUID, db: AsyncSession = Depends(get_db), user: User = Depends(get_current_user)):
    """Evaluation status of the saved post (current / stale / not evaluated) with the latest result and history."""
    return await EvaluationService(db, user.id).state(project_id)


@router.post("/{project_id}/evaluation", response_model=Dict[str, Any])
async def evaluate(project_id: UUID, body: EvaluateRequest, db: AsyncSession = Depends(get_db),
                   user: User = Depends(get_current_user)):
    """Evaluate the saved post version (rule-based; no AI call). Never changes the post; adds to the history."""
    service = EvaluationService(db, user.id)
    await service.evaluate(project_id, body.version)
    return await service.state(project_id)
