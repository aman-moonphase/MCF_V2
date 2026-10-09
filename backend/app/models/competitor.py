import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from app.db.base_class import Base


class Competitor(Base):
    """A competitor of a Product. Stored at Product level so every campaign of the product shares it."""

    __tablename__ = "competitors"
    __table_args__ = (UniqueConstraint("product_id", "name", name="uq_competitors_product_name"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)

    name = Column(String(255), nullable=False)
    website_url = Column(String(1024), nullable=True)
    description = Column(Text, nullable=True)  # what the user knows about their product/positioning
    notes = Column(Text, nullable=True)  # the user's own observations

    # user | product_sources (named in our own sources) | ai_suggested (unverified candidate)
    origin = Column(String(30), nullable=False, default="user")
    suggestion_reason = Column(Text, nullable=True)

    # not_analyzed | analyzed | insufficient_evidence | failed
    analysis_status = Column(String(30), nullable=False, default="not_analyzed")
    analysis = Column(JSONB, nullable=True)
    analysis_error = Column(Text, nullable=True)
    last_analyzed_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    evidence = relationship("CompetitorEvidence", back_populates="competitor", cascade="all, delete-orphan",
                            order_by="CompetitorEvidence.created_at")


class CompetitorEvidence(Base):
    """Evidence about a competitor. Kept apart from a project's own source documents (source_documents)."""

    __tablename__ = "competitor_evidence"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id = Column(UUID(as_uuid=True), ForeignKey("competitors.id", ondelete="CASCADE"), nullable=False, index=True)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)

    evidence_type = Column(String(20), nullable=False)  # url | note | pdf
    source_url = Column(String(1024), nullable=True)
    title = Column(String(255), nullable=True)
    content = Column(Text, nullable=True)  # full extracted text
    # completed | failed | not_fetched (e.g. social platforms MCF does not scrape)
    status = Column(String(20), nullable=False, default="completed")
    error = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    competitor = relationship("Competitor", back_populates="evidence")
