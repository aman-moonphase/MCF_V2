import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class Product(Base):
    """A product being promoted. One product → many projects (campaigns).

    Holds the reusable Product Profile learned in the Product Understanding stage. Projects
    reference it via projects.product_id; the profile is never copied into projects.
    """

    __tablename__ = "products"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)

    # Product Understanding
    # not_started | needs_clarification | ready_for_review | approved
    understanding_status = Column(String(50), nullable=False, default="not_started", server_default="not_started")
    profile = Column(JSONB, nullable=True)  # ProductProfile (app/ai/product_schemas.py)
    # [{id, question, why_it_matters, fields, status: open|answered|resolved, answer, answered_at}]
    clarification_questions = Column(JSONB, nullable=True)
    edited_fields = Column(JSONB, nullable=True)  # profile fields the user edited by hand
    profile_version = Column(Integer, nullable=False, default=0, server_default="0")
    approved_version = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)

    # Competitor Analysis (competitors themselves live in the competitors table)
    # not_started | in_progress | ready_for_review | approved
    competitor_analysis_status = Column(String(50), nullable=False, default="not_started", server_default="not_started")
    competitor_version = Column(Integer, nullable=False, default=0, server_default="0")  # bumps on any competitor change
    competitor_comparison = Column(JSONB, nullable=True)
    competitor_comparison_version = Column(Integer, nullable=True)  # competitor_version it was built from
    competitor_comparison_at = Column(DateTime(timezone=True), nullable=True)
    competitor_approved_version = Column(Integer, nullable=True)
    competitor_approved_at = Column(DateTime(timezone=True), nullable=True)
    # True when the user explicitly approved Competitor Analysis with limited/no evidence.
    competitor_limited_evidence = Column(Boolean, nullable=False, default=False, server_default="false")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    owner = relationship("User")
    projects = relationship("Project", back_populates="product")
