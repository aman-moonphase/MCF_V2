import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base_class import Base


class PromotionStrategy(Base):
    """The product-level promotion plan, shared by every campaign (project) of the Product.

    Campaign-specific choices (e.g. a Content Type override) are stored on the project's own
    workflow stage, so they never silently change this shared plan.
    """

    __tablename__ = "promotion_strategies"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)

    strategy = Column(JSONB, nullable=False)  # PromotionStrategyOutput after grounding (app/ai/strategy_schemas.py)
    status = Column(String(30), nullable=False, default="draft")  # draft | approved
    version = Column(Integer, nullable=False, default=1)
    approved_version = Column(Integer, nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    edited_sections = Column(JSONB, nullable=True)

    # What it was generated from: {profile_version, competitor_version, limited_evidence, competitors: [...]}
    basis = Column(JSONB, nullable=True)
    provider = Column(String(30), nullable=True)
    generated_at = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))
