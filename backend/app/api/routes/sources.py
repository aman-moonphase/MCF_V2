from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, Optional
from uuid import UUID, uuid4
import os
import re

from ...db.session import get_db
from ...models.source import SourceDocument
from ...services.project_service import ProjectService
from ...services.ingestion_service import IngestionError, IngestionService
from ...ai.config import build_embedding_config
from ...api.deps import get_current_user
from ...core.config import settings
from ...core.uploads import save_upload_limited
from ...core.url_safety import UnsafeURLError, validate_public_url

router = APIRouter()

TEMP_UPLOAD_DIR = os.path.join(os.getcwd(), "temp_uploads")


def safe_display_name(filename: Optional[str]) -> str:
    """A display-only name for an uploaded file: basename, no path parts or control characters."""
    name = os.path.basename((filename or "").replace("\\", "/"))
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    return (name or "upload.pdf")[:200]


def temp_upload_path(upload_dir: str = TEMP_UPLOAD_DIR) -> str:
    """A server-generated path inside the upload directory. The client filename is never used in the path."""
    base = os.path.realpath(upload_dir)
    path = os.path.realpath(os.path.join(base, f"{uuid4().hex}.pdf"))
    if os.path.commonpath([base, path]) != base:
        raise HTTPException(status_code=400, detail="Invalid upload path")
    return path


@router.post("/{project_id}/sources/ingest", response_model=Dict[str, Any])
async def ingest_source(
    project_id: str,
    source_type: str = Form(...),
    content: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """
    Ingest a source document for a project (URL, Text, or PDF File).
    """
    try:
        project_uuid = UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid project_id format")

    project_service = ProjectService(db, current_user.id)
    await project_service.get_project(project_uuid)
    # Automatically raises 404 if project not found

    config = build_embedding_config()

    # Process inputs based on type
    file_path = None
    url = None
    text = None
    display_name = f"Ingested {source_type}"

    if source_type == "url":
        if not content:
            raise HTTPException(status_code=400, detail="URL content is required")
        try:
            url = validate_public_url(content, allow_private=settings.ALLOW_PRIVATE_URL_INGESTION)
        except UnsafeURLError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif source_type == "text":
        if not content:
            raise HTTPException(status_code=400, detail="Text content is required")
        if len(content) > settings.RAG_MAX_SOURCE_CHARS:  # refuse before anything is stored
            raise HTTPException(status_code=422, detail=f"The source is too large to index ({len(content):,} characters; "
                                                        f"the limit is {settings.RAG_MAX_SOURCE_CHARS:,}). Split it into smaller sources.")
        text = content
    elif source_type == "pdf":
        if not file:
            raise HTTPException(status_code=400, detail="PDF file is required")

        # Save the upload under a server-generated name; the client filename is display-only.
        os.makedirs(TEMP_UPLOAD_DIR, exist_ok=True)
        file_path = temp_upload_path()
        display_name = safe_display_name(file.filename)
        await save_upload_limited(file, file_path, settings.MAX_UPLOAD_BYTES)  # 413 (and no file left) when too large
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported source type: {source_type}")

    try:
        # Create SourceDocument first
        metadata = {}
        source_url = None
        if source_type == "url":
            source_url = url
        elif source_type == "text":
            metadata["raw_text"] = text
        elif source_type == "pdf" and file_path:
            metadata["file_path"] = file_path
            metadata["original_filename"] = display_name

        source_doc = SourceDocument(
            project_id=project_uuid,
            source_type=source_type if source_type != "pdf" else "upload",
            name=display_name,
            source_url=source_url,
            metadata_=metadata
        )
        db.add(source_doc)
        await db.commit()
        await db.refresh(source_doc)

        source = await IngestionService.ingest_source(
            db=db,
            project_id=project_uuid,
            source_id=source_doc.id,
            config=config
        )

        # Clean up file
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

        from sqlalchemy import select, func
        from ...models.source import DocumentChunk
        chunks_created = await db.scalar(
            select(func.count(DocumentChunk.id))
            .where(DocumentChunk.source_document_id == source.id)
        )

        if source.status == "duplicate":
            duplicate_of = (source.metadata_ or {}).get("duplicate_of")
            return {
                "id": str(source.id),
                "project_id": str(source.project_id),
                "source_type": source.source_type,
                "title": source.name,
                "status": "Duplicate",
                "message": "This content is already indexed in this project; it was not indexed again.",
                "duplicate_of": duplicate_of,
                "chunks_created": 0,
                "characters_extracted": 0,
            }
        return {
            "id": str(source.id),
            "project_id": str(source.project_id),
            "source_type": source.source_type,
            "title": source.name,
            "status": "Success",
            "message": f"Successfully ingested {source_type}",
            "chunks_created": chunks_created or 0,
            "characters_extracted": len(source.extracted_text or ""),
        }
    except IngestionError as e:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        # Note user requirement: Never silently return fake success for real ingestion failures.
        raise HTTPException(status_code=500, detail=f"Failed to ingest source: {repr(e)}")


@router.post("/{project_id}/sources/{source_id}/reindex", response_model=Dict[str, Any])
async def reindex_source(
    project_id: UUID,
    source_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: Any = Depends(get_current_user)
):
    """Rebuild a source's chunks from its stored full text with the configured embedding provider (e.g. after the
    embedding provider changed). The project must belong to the current user."""
    await ProjectService(db, current_user.id).get_project(project_id)
    try:
        source = await IngestionService.reindex_source(db, project_id, source_id, build_embedding_config())
    except IngestionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError:
        raise HTTPException(status_code=404, detail="Source not found")
    meta = source.metadata_ or {}
    return {"id": str(source.id), "status": "Reindexed", "chunks_created": meta.get("chunk_count", 0),
            "embedding_provider": meta.get("embedding_provider"), "embedding_model": meta.get("embedding_model")}
