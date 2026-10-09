import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from pgvector.sqlalchemy import Vector
from app.db.base_class import Base

class SourceDocument(Base):
    __tablename__ = "source_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    source_type = Column(String(50), nullable=False) # upload, url, text
    name = Column(String(255), nullable=False)
    source_url = Column(String(1024), nullable=True)
    mime_type = Column(String(100), nullable=True)
    
    status = Column(String(50), nullable=False, default="pending") # pending, processing, completed, failed
    metadata_ = Column("metadata", JSONB, nullable=True)
    # Full extracted text of the source (typed text, PDF text, or page text). This is the canonical,
    # untruncated source the AI pipeline reads; chunks below are derived from it for retrieval.
    extracted_text = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relationships
    project = relationship("Project", back_populates="sources")
    chunks = relationship("DocumentChunk", back_populates="source_document", cascade="all, delete-orphan", order_by="DocumentChunk.chunk_index")


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_document_id = Column(UUID(as_uuid=True), ForeignKey("source_documents.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    
    chunk_index = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    metadata_ = Column("metadata", JSONB, nullable=True)
    
    # Using 1536 as default for text-embedding-3-small / text-embedding-ada-002
    embedding = Column(Vector(1536), nullable=True) 
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    # Relationships
    source_document = relationship("SourceDocument", back_populates="chunks")
