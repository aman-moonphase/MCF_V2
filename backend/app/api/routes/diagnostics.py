from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.diagnostics import DiagnosticsResponse
from app.services.diagnostics_service import collect_diagnostics

router = APIRouter()


@router.get("", response_model=DiagnosticsResponse)
async def get_diagnostics(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    """Read-only health overview (signed-in users only). Makes no writes and no AI / embedding / external calls,
    returns no secrets, and reports ingestion figures for the caller's own projects only."""
    return await collect_diagnostics(db, current_user.id)
