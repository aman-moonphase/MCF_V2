import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, String, Text, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from app.db.base_class import Base


class ContentImage(Base):
    """An optional creative image asset associated with a saved post version.

    Associated with a specific project and generated_contents row at content_version.
    Generating or updating an image NEVER alters post approval status, stage completion,
    or publication/scheduling status.
    """

    __tablename__ = "content_images"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    generated_content_id = Column(UUID(as_uuid=True), ForeignKey("generated_contents.id", ondelete="CASCADE"),
                                  nullable=False, index=True)
    content_version = Column(Integer, nullable=False, index=True)

    prompt = Column(Text, nullable=False)
    alt_text = Column(String(500), nullable=False)
    image_url = Column(Text, nullable=False)
    aspect_ratio = Column(String(20), nullable=False, default="16:9")
    style = Column(String(50), nullable=False, default="professional")
    provider = Column(String(30), nullable=False, default="demo")
    is_demo = Column(Boolean, nullable=False, default=True)
    status = Column(String(30), nullable=False, default="generated")

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                        onupdate=lambda: datetime.now(timezone.utc))
