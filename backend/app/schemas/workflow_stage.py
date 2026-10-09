from pydantic import BaseModel, ConfigDict, computed_field
from typing import Optional, Any
from datetime import datetime
from uuid import UUID

from app.core.workflow import stage_label, stage_order


class WorkflowStageBase(BaseModel):
    stage_type: str
    status: str

class WorkflowStageCreate(WorkflowStageBase):
    data: Optional[Any] = None

class WorkflowStageUpdate(BaseModel):
    status: Optional[str] = None
    data: Optional[Any] = None

class WorkflowStageResponse(WorkflowStageBase):
    id: UUID
    project_id: UUID
    data: Optional[Any] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @computed_field
    @property
    def label(self) -> str:
        """Display name from the canonical workflow definition (app/core/workflow.py)."""
        return stage_label(self.stage_type)

    @computed_field
    @property
    def order(self) -> int:
        return stage_order(self.stage_type)
