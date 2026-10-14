import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, UniqueConstraint, event
from sqlalchemy.dialects.postgresql import JSONB, UUID, insert

from app.db.base_class import Base
from app.models.generated_content import GeneratedContent


class GeneratedContentVersion(Base):
    """History of a project's generated post, one row per version.

    GeneratedContent holds only the CURRENT post and is overwritten in place when it is regenerated or hand-edited
    (version + 1). This table keeps what every version contained, including a person's hand edits, so nothing is lost
    when a later version replaces it. Written by the ORM listeners below on every insert/update of the current post;
    the only field that changes on an existing row is its approval state.
    """

    __tablename__ = "generated_content_versions"
    __table_args__ = (UniqueConstraint("generated_content_id", "version", name="uq_generated_content_version"),)

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    generated_content_id = Column(UUID(as_uuid=True), ForeignKey("generated_contents.id", ondelete="CASCADE"), nullable=False, index=True)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    version = Column(Integer, nullable=False)
    content = Column(JSONB, nullable=False)
    validation = Column(JSONB, nullable=True)
    status = Column(String(30), nullable=False, default="draft")  # draft | approved (this exact version)
    edited = Column(Boolean, nullable=False, default=False)  # True when this version is a person's hand edit
    context_snapshot = Column(JSONB, nullable=True)
    provider = Column(String(30), nullable=True)
    is_demo = Column(Boolean, nullable=False, default=False)
    generated_at = Column(DateTime(timezone=True), nullable=True)
    edited_at = Column(DateTime(timezone=True), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def _snapshot(mapper, connection, target: GeneratedContent) -> None:
    approved = target.status == "approved" and target.approved_version == target.version
    now = datetime.now(timezone.utc)
    values = {
        "content": target.content, "validation": target.validation, "status": "approved" if approved else "draft",
        "edited": bool(target.edited), "context_snapshot": target.context_snapshot, "provider": target.provider,
        "is_demo": bool(target.is_demo), "generated_at": target.generated_at, "edited_at": target.edited_at,
        "approved_at": target.approved_at if approved else None, "updated_at": now,
    }
    statement = insert(GeneratedContentVersion.__table__).values(
        id=uuid.uuid4(), generated_content_id=target.id, project_id=target.project_id, version=target.version, created_at=now, **values)
    connection.execute(statement.on_conflict_do_update(constraint="uq_generated_content_version", set_=values))


event.listen(GeneratedContent, "after_insert", _snapshot)
event.listen(GeneratedContent, "after_update", _snapshot)
