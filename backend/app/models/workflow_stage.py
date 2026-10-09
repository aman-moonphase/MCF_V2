import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class WorkflowStage(Base):
    __tablename__ = "workflow_stages"
    # A project has at most one row per stage type.
    __table_args__ = (UniqueConstraint("project_id", "stage_type", name="uq_workflow_stages_project_stage"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    stage_type = Column(String(100), nullable=False)
    status = Column(String(50), nullable=False, default="Locked")
    
    data = Column(JSONB, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship to Project
    project = relationship("Project", back_populates="stages")
