import uuid
from datetime import datetime, timezone
from sqlalchemy import CheckConstraint, Column, String, DateTime, ForeignKey, Index, Integer, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.db.base_class import Base

class Schedule(Base):
    """A planned calendar entry. Planning only: nothing here publishes or posts anything.

    Legacy entries (created before content planning) have no product/post reference; their values are kept as-is.
    A plan for a saved post records the post, the exact version planned and a fingerprint of its content, so a
    later change to the post can be detected. Schema: alembic f6a7b8c9d0e1.
    """
    __tablename__ = "schedules"
    __table_args__ = (
        CheckConstraint("generated_content_id IS NULL OR content_version IS NOT NULL", name="ck_schedules_post_version"),
        Index("ix_schedules_project_id_scheduled_at", "project_id", "scheduled_at"),
        # One active (not cancelled) plan per post version, platform and time; legacy rows without a post are exempt.
        Index("uq_schedules_active_plan", "generated_content_id", "content_version", "platform", "scheduled_at",
              unique=True, postgresql_where=text("cancelled_at IS NULL AND generated_content_id IS NOT NULL")),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(100), nullable=False)
    scheduled_at = Column(DateTime(timezone=True), nullable=False, index=True)
    status = Column(String(50), nullable=False, default="Scheduled")

    # Content planning (all optional, so legacy entries stay valid)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="SET NULL", name="fk_schedules_product_id"),
                        nullable=True, index=True)
    generated_content_id = Column(UUID(as_uuid=True), ForeignKey("generated_contents.id", ondelete="SET NULL",
                                                                 name="fk_schedules_generated_content_id"),
                                  nullable=True, index=True)
    content_version = Column(Integer, nullable=True)  # the saved post version this entry plans
    content_digest = Column(String(64), nullable=True)  # fingerprint of that version's content
    content_type = Column(String(50), nullable=True)
    timezone = Column(String(64), nullable=True)  # IANA name the user planned in, e.g. "Asia/Kolkata"
    notes = Column(Text, nullable=True)
    lock_version = Column(Integer, nullable=False, default=1, server_default="1")  # optimistic concurrency
    cancelled_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationship back to project
    project = relationship("Project", back_populates="schedules")
