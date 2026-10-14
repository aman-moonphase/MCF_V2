import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert

from app.db.base_class import Base
from app.models.promotion_strategy import PromotionStrategy


class PromotionStrategyVersion(Base):
    """Immutable-by-convention history of a product's promotion strategy, one row per version.

    PromotionStrategy holds only the CURRENT strategy and edits it in place (version + 1). This table keeps what
    each version contained, so an approved version survives later edits and can be inspected. It is written by
    the ORM listeners below, on every insert/update of the current strategy, so no service has to remember to do it.
    The only field that changes on an existing row is its approval state (approving version N updates row N).
    """

    __tablename__ = "promotion_strategy_versions"
    __table_args__ = (UniqueConstraint("product_id", "version", name="uq_strategy_version_product_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id = Column(UUID(as_uuid=True), ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    strategy = Column(JSONB, nullable=False)
    status = Column(String(30), nullable=False, default="draft")  # draft | approved (this exact version)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    edited_sections = Column(JSONB, nullable=True)
    basis = Column(JSONB, nullable=True)
    provider = Column(String(30), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _snapshot(mapper, connection, target: PromotionStrategy) -> None:
    approved = target.status == "approved" and target.approved_version == target.version
    now = datetime.now(timezone.utc)
    values = {
        "strategy": target.strategy,
        "status": "approved" if approved else "draft",
        "approved_at": target.approved_at if approved else None,
        "edited_sections": target.edited_sections,
        "basis": target.basis,
        "provider": target.provider,
        "updated_at": now,
    }
    statement = insert(PromotionStrategyVersion.__table__).values(
        id=uuid.uuid4(), product_id=target.product_id, version=target.version, created_at=now, **values)
    connection.execute(statement.on_conflict_do_update(constraint="uq_strategy_version_product_version", set_=values))


event.listen(PromotionStrategy, "after_insert", _snapshot)
event.listen(PromotionStrategy, "after_update", _snapshot)
