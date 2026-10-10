import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base_class import Base


class GeneratedContent(Base):
    """The current generated asset of a project (campaign) for one content type and platform.

    One row per (project, content_type, platform). Regenerating or editing bumps `version`; an
    approved asset is never overwritten (the service refuses). A later version-history table can
    snapshot rows by (id, version) without changing this one.
    """

    __tablename__ = "generated_contents"
    __table_args__ = (UniqueConstraint("project_id", "content_type", "platform", name="uq_generated_content_project_type_platform"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    content_type = Column(String(50), nullable=False)  # e.g. "Social Post"
    platform = Column(String(30), nullable=False)  # e.g. "linkedin"

    content = Column(JSONB, nullable=False)  # LinkedInPostOutput after validation (app/ai/generation_schemas.py)
    validation = Column(JSONB, nullable=True)  # warnings, unsupported claims, character count, limit
    # draft | approved (approval belongs to the later Review stage; reserved here so drafts can't overwrite it)
    status = Column(String(30), nullable=False, default="draft")
    version = Column(Integer, nullable=False, default=1)
    edited = Column(Boolean, nullable=False, default=False)

    # What it was generated from: product, profile/competitor/strategy versions, pillar, instructions
    context_snapshot = Column(JSONB, nullable=True)
    provider = Column(String(30), nullable=True)
    is_demo = Column(Boolean, nullable=False, default=False)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    edited_at = Column(DateTime(timezone=True), nullable=True)
    # Human approval in the Review Approval stage: the exact saved version that was approved. Approval only
    # records the decision; nothing is published, scheduled or sent anywhere.
    approved_version = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    # Real-provider API usage of the request(s) that generated this post (app/ai/usage.py::summarize_usage):
    # token counts, duration, estimated cost, and the version it produced. None for Demo Mode (no API calls).
    # Manual edits keep it: it describes the generation, not the edit.
    usage = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
