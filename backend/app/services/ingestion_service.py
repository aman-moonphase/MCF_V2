"""Source ingestion: extract → validate → de-duplicate → chunk → embed → index, with provenance.

Guarantees:
- The full extracted text is kept on the SourceDocument (canonical source); chunks are derived from it.
- Every chunk records its source document, character range, page (PDF), content hash, the source's content hash
  and the embedding provider/model that produced its vector — so stale or incompatible chunks can be detected
  and are never silently used (see RetrievalService).
- Indexing replaces a source's chunks atomically: old chunks are deleted in the same transaction, and a failure
  rolls back every chunk written in the attempt (the source is then marked failed with the reason).
- Empty text, oversized input and duplicates of an already indexed source in the same project are handled
  explicitly (IngestionError carries a user-facing message).
"""

import uuid
from datetime import datetime, timezone
from typing import Dict, List

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import AIConfig
from app.ai.providers.embedding.factory import EmbeddingProviderFactory
from app.models.source import DocumentChunk, SourceDocument
from app.services.chunking_service import ChunkingService, content_hash
from app.services.extraction_service import ExtractionResult, ExtractionService

INDEX_VERSION = 2
_FAILED_STATUSES = ("failed", "duplicate")


class IngestionError(ValueError):
    """An ingestion problem caused by the input (shown to the user), not a server fault."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionService:
    @staticmethod
    async def _get_source(db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID) -> SourceDocument:
        source = (await db.execute(select(SourceDocument).where(
            SourceDocument.id == source_id, SourceDocument.project_id == project_id))).scalar_one_or_none()
        if not source:
            raise ValueError(f"SourceDocument {source_id} not found")
        return source

    @staticmethod
    def _extract(source: SourceDocument) -> ExtractionResult:
        meta = dict(source.metadata_ or {})
        if source.source_type == "text":
            return ExtractionService.extract_from_text(meta.get("raw_text", ""), metadata=meta)
        if source.source_type == "url":
            return ExtractionService.extract_from_url(source.source_url, metadata=meta)
        if source.source_type == "upload":
            file_path = meta.get("file_path")
            if not file_path:
                raise ValueError("No file_path provided for uploaded source")
            with open(file_path, "rb") as f:
                return ExtractionService.extract_from_pdf(f.read(), metadata=meta)
        raise ValueError(f"Unknown source_type: {source.source_type}")

    @staticmethod
    async def _index(db: AsyncSession, project_id: uuid.UUID, source: SourceDocument, text: str, meta: Dict,
                     config: AIConfig) -> int:
        """Replace the source's chunks with a fresh index of `text`. Caller commits."""
        from app.core.config import settings

        source_hash = content_hash(text)
        base = {**meta, "source_type": source.source_type, "source_url": source.source_url, "title": meta.get("title") or source.name}
        chunks = ChunkingService.chunk_text(text, base, page_ranges=meta.get("page_ranges"), page_numbers=meta.get("page_numbers"))
        if not chunks:
            raise IngestionError("The source has no text to index.")

        provider = EmbeddingProviderFactory.get_provider(config)
        vectors: List[List[float]] = []
        batch = max(1, settings.RAG_EMBED_BATCH_SIZE)
        for i in range(0, len(chunks), batch):
            vectors += await provider.embed_documents([c.content for c in chunks[i:i + batch]])
        if len(vectors) != len(chunks):
            raise ValueError("The embedding provider returned a different number of vectors than chunks.")

        await db.execute(delete(DocumentChunk).where(DocumentChunk.source_document_id == source.id))
        for chunk, vector in zip(chunks, vectors):
            db.add(DocumentChunk(
                source_document_id=source.id, project_id=project_id, chunk_index=chunk.chunk_index,
                content=chunk.content, token_count=chunk.token_count, embedding=vector,
                metadata_={**chunk.metadata, "source_document_id": str(source.id), "source_name": source.name,
                           "source_content_hash": source_hash, "embedding_provider": provider.provider_name,
                           "embedding_model": provider.model_name, "index_version": INDEX_VERSION},
            ))
        source.metadata_ = {**(source.metadata_ or {}), "content_hash": source_hash, "char_count": len(text),
                            "chunk_count": len(chunks), "embedding_provider": provider.provider_name,
                            "embedding_model": provider.model_name, "index_version": INDEX_VERSION, "indexed_at": _now()}
        return len(chunks)

    @staticmethod
    async def _fail(db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, error: Exception) -> None:
        await db.rollback()  # discard any chunks written during this attempt
        source = await IngestionService._get_source(db, project_id, source_id)
        source.status = "failed"
        source.metadata_ = {**(source.metadata_ or {}), "error": str(error)}
        await db.commit()

    @staticmethod
    async def ingest_source(db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, config: AIConfig) -> SourceDocument:
        """Extract, validate and index a new SourceDocument. A duplicate of an already indexed source in the same
        project is marked status="duplicate" (metadata.duplicate_of) and not indexed again."""
        from app.core.config import settings

        source = await IngestionService._get_source(db, project_id, source_id)
        source.status = "processing"
        await db.commit()
        try:
            try:
                extracted = IngestionService._extract(source)
            except ValueError as e:
                if "Empty" in str(e) or "No text" in str(e) or "Could not extract any text" in str(e):
                    raise IngestionError(f"The source has no extractable text ({e}).") from e
                # Extractors raise ValueError for problems with the INPUT (corrupt PDF, unreachable or unsafe URL):
                # a clear 422 for the user, not a server error.
                raise IngestionError(str(e)) from e
            text = extracted.text
            if not text or not text.strip():
                raise IngestionError("The source has no extractable text.")
            if len(text) > settings.RAG_MAX_SOURCE_CHARS:
                raise IngestionError(f"The source is too large to index ({len(text):,} characters; the limit is "
                                     f"{settings.RAG_MAX_SOURCE_CHARS:,}). Split it into smaller sources.")

            source_hash = content_hash(text)
            existing = (await db.execute(select(SourceDocument).where(
                SourceDocument.project_id == project_id, SourceDocument.id != source.id,
                SourceDocument.status == "completed"))).scalars().all()
            duplicate = next((d for d in existing if (d.metadata_ or {}).get("content_hash") == source_hash
                              or (not (d.metadata_ or {}).get("content_hash") and d.extracted_text
                                  and content_hash(d.extracted_text) == source_hash)), None)
            meta = {k: v for k, v in (extracted.metadata or {}).items() if k != "error"}
            source.metadata_ = {**meta, "content_hash": source_hash}
            if duplicate:
                source.status = "duplicate"
                source.metadata_ = {**source.metadata_, "duplicate_of": str(duplicate.id)}
                await db.commit()
                return source

            await IngestionService._index(db, project_id, source, text, meta, config)
            source.extracted_text = text
            source.status = "completed"
            await db.commit()
            return source
        except Exception as e:
            await IngestionService._fail(db, project_id, source_id, e)
            raise

    @staticmethod
    async def reindex_source(db: AsyncSession, project_id: uuid.UUID, source_id: uuid.UUID, config: AIConfig) -> SourceDocument:
        """Rebuild a completed source's chunks from its stored full text with the configured embedding provider
        (after its text changed, or the embedding provider/model changed). Old chunks are replaced atomically."""
        source = await IngestionService._get_source(db, project_id, source_id)
        if source.status != "completed" or not (source.extracted_text or "").strip():
            raise IngestionError("Only successfully ingested sources with extracted text can be re-indexed.")
        meta = {k: v for k, v in (source.metadata_ or {}).items() if k != "error"}
        try:
            await IngestionService._index(db, project_id, source, source.extracted_text, meta, config)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
        return await IngestionService._get_source(db, project_id, source_id)
