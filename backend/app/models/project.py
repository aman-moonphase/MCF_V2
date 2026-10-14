import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Enum, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Project(Base):
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    status = Column(String(50), nullable=False, default="Draft")
    source_type = Column(String(100), nullable=False)
    source_reference = Column(String(500), nullable=False)
    current_stage = Column(String(100), nullable=False, default="source-grounding")
    # Trace of the most recent workflow run (when, outcome, stages visited, redacted errors). See WorkflowOrchestrationService.
    last_workflow_run = Column(JSONB, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Owner Relationship
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    owner = relationship("User", back_populates="projects")

    # Optional product this project (campaign) promotes. Deleting a product keeps its projects.
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL"), nullable=True, index=True)
    product = relationship("Product", back_populates="projects")

    # Relationship to WorkflowStage
    stages = relationship("WorkflowStage", back_populates="project", cascade="all, delete-orphan", order_by="WorkflowStage.created_at")

    # Relationship to Schedules
    schedules = relationship("Schedule", back_populates="project", cascade="all, delete-orphan", order_by="Schedule.scheduled_at")

    # Relationship to SourceDocuments
    sources = relationship("SourceDocument", back_populates="project", cascade="all, delete-orphan")
