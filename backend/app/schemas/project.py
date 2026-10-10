from pydantic import BaseModel, ConfigDict, Field, field_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from app.core.workflow import visible_stage_types, stage_order
from app.schemas.workflow_stage import WorkflowStageResponse

class ProjectBase(BaseModel):
    title: str = Field(max_length=255)
    description: Optional[str] = None
    source_type: str = Field(max_length=100)
    # A short reference/preview only (URL, filename, or the start of a text idea).
    # The full source is stored on the project's SourceDocument rows, not here.
    source_reference: str = Field(max_length=500)

class ProjectCreate(ProjectBase):
    pass

class ProjectUpdate(BaseModel):
    title: Optional[str] = Field(default=None, max_length=255)
    description: Optional[str] = None
    status: Optional[str] = None
    source_type: Optional[str] = Field(default=None, max_length=100)
    source_reference: Optional[str] = Field(default=None, max_length=500)
    current_stage: Optional[str] = None

class ProjectResponse(ProjectBase):
    id: UUID
    status: str
    current_stage: str
    # The Product this project (campaign) promotes; its profile lives on the product, not here.
    product_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime
    stages: List[WorkflowStageResponse] = []

    model_config = ConfigDict(from_attributes=True)

    @field_validator("stages")
    @classmethod
    def order_stages(cls, stages: List[WorkflowStageResponse]) -> List[WorkflowStageResponse]:
        # Canonical workflow order (app/core/workflow.py), not row creation time. Product-workflow
        # projects created before the legacy stages were dropped keep those rows, but don't show them.
        visible = visible_stage_types([stage.stage_type for stage in stages])
        return sorted((s for s in stages if s.stage_type in visible), key=lambda stage: stage_order(stage.stage_type))
