import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.db.base_class import Base


class ContentEvaluation(Base):
    """One evaluation of one saved version of a generated post (Evaluate & Improve stage).

    Append-only history: re-evaluating adds a row; nothing is overwritten. An evaluation is "current" only while
    `content_version` equals the post's version — any saved edit or regeneration bumps the version and makes it stale.
    Evaluation never changes the post itself.
    """

    __tablename__ = "content_evaluations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_content_id = Column(UUID(as_uuid=True), ForeignKey("generated_contents.id", ondelete="CASCADE"),
                                  nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    content_version = Column(Integer, nullable=False)  # the exact generated_contents.version evaluated

    evaluator = Column(String(50), nullable=False)  # e.g. "rules-v1" (app/ai/evaluation)
    mode = Column(String(30), nullable=False)  # "rule-based" (deterministic) — a future AI evaluator would say so
    overall = Column(String(40), nullable=False)  # ready | ready_with_recommendations | needs_improvement | not_ready
    result = Column(JSONB, nullable=False)  # overall explanation, dimensions, findings, counts

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
