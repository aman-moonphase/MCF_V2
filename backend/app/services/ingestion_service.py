import uuid
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from app.models.source import SourceDocument, DocumentChunk
from app.services.extraction_service import ExtractionService, ExtractionResult
from app.services.chunking_service import ChunkingService, ChunkResult
from app.ai.providers.embedding.base import BaseEmbeddingProvider
from app.ai.providers.embedding.factory import EmbeddingProviderFactory
from app.ai.config import AIConfig

class IngestionService:
    @staticmethod
    async def ingest_source(
        db: AsyncSession, 
        project_id: uuid.UUID,
        source_id: uuid.UUID,
        config: AIConfig
    ) -> SourceDocument:
        """
        Orchestrates the ingestion pipeline for a given SourceDocument.
        """
        # 1. Fetch the source document
        result = await db.execute(
            select(SourceDocument).where(
                SourceDocument.id == source_id, 
                SourceDocument.project_id == project_id
            )
        )
        source = result.scalar_one_or_none()
        if not source:
            raise ValueError(f"SourceDocument {source_id} not found")

        # Mark as processing
        source.status = "processing"
        await db.commit()

        try:
            # 2. Extract
            extract_result: ExtractionResult
            if source.source_type == "text":
                text_content = source.metadata_.get("raw_text", "")
                extract_result = ExtractionService.extract_from_text(text_content, metadata=source.metadata_)
            elif source.source_type == "url":
                extract_result = ExtractionService.extract_from_url(source.source_url, metadata=source.metadata_)
            elif source.source_type == "upload":
                # Assuming raw bytes are stored in metadata temporarily or we have to fetch them. 
                # For this implementation, we will assume PDF raw_bytes is in metadata for simplicity, or 
                # ideally it would be read from a file store. We'll check metadata for 'raw_bytes'.
                # Actually, JSON can't store raw bytes efficiently. Usually, an upload writes to a temp file or S3.
                # If we need to support PDF upload ingestion here, we need the bytes.
                # For now, let's assume `raw_bytes` might be passed or it's a text upload.
                # Since we don't have a file store, let's assume the bytes are available or the caller handles the file reading 
                # and just passes the text to `ingest_source`, or we do it beforehand. 
                # Wait, the user requirement is PDF upload. We'll assume the API endpoint saves it to disk or passes it to the service.
                # Let's adjust to read from disk if file_path is in metadata.
                file_path = source.metadata_.get("file_path")
                if not file_path:
                     raise ValueError("No file_path provided for uploaded source")
                with open(file_path, "rb") as f:
                    file_content = f.read()
                extract_result = ExtractionService.extract_from_pdf(file_content, metadata=source.metadata_)
            else:
                raise ValueError(f"Unknown source_type: {source.source_type}")

            # 3. Chunk
            chunks = ChunkingService.chunk_text(
                text=extract_result.text,
                base_metadata=extract_result.metadata
            )

            if not chunks:
                raise ValueError("Extraction resulted in no text chunks")

            # 4. Embed
            embedding_provider = EmbeddingProviderFactory.get_provider(config)
            texts_to_embed = [chunk.content for chunk in chunks]
            
            # OpenAI limit is typically large, but batching is better if many chunks.
            # We will embed all chunks together for simplicity
            embeddings = await embedding_provider.embed_documents(texts_to_embed)

            # 5. Persist Chunks
            db_chunks = []
            for i, chunk in enumerate(chunks):
                db_chunk = DocumentChunk(
                    source_document_id=source.id,
                    project_id=project_id,
                    chunk_index=chunk.chunk_index,
                    content=chunk.content,
                    token_count=chunk.token_count,
                    metadata_=chunk.metadata,
                    embedding=embeddings[i] if embeddings else None
                )
                db_chunks.append(db_chunk)
                db.add(db_chunk)

            # Mark as completed and keep the full extracted text as the canonical source
            source.extracted_text = extract_result.text
            source.status = "completed"
            source.metadata_ = extract_result.metadata # Update with extracted meta
            await db.commit()
            
            return source

        except Exception as e:
            # Mark as failed
            source.status = "failed"
            source.metadata_ = source.metadata_ or {}
            source.metadata_["error"] = str(e)
            await db.commit()
            raise e
