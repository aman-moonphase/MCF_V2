"""Reads a project's complete source text for the AI pipeline.

The canonical store is SourceDocument.extracted_text (set at ingestion). `projects.source_reference`
is only a short reference/preview (max 500 chars) and is never used as the AI's source when an
ingested source exists.
"""

from typing import List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.project import Project
from app.models.source import DocumentChunk, SourceDocument


async def _chunk_text(db: AsyncSession, source_id) -> str:
    """Fallback for sources ingested before extracted_text existed: rebuild from ordered chunks."""
    result = await db.execute(
        select(DocumentChunk.content)
        .where(DocumentChunk.source_document_id == source_id)
        .order_by(DocumentChunk.chunk_index.asc())
    )
    return "\n".join(result.scalars().all())


async def get_project_source_texts(db: AsyncSession, project: Project) -> List[tuple[str, str]]:
    """(name, full text) for every successfully ingested source of the project, oldest first."""
    result = await db.execute(
        select(SourceDocument)
        .where(SourceDocument.project_id == project.id, SourceDocument.status == "completed")
        .order_by(SourceDocument.created_at.asc())
    )
    texts = []
    for doc in result.scalars().all():
        text = doc.extracted_text or (doc.metadata_ or {}).get("raw_text") or await _chunk_text(db, doc.id)
        if text and text.strip():
            texts.append((doc.name, text.strip()))
    return texts


def cap_for_prompt(text: str, limit: int | None = None) -> str:
    """Bound the text placed in a single prompt, stating the cut explicitly (never silently)."""
    limit = limit or settings.AI_MAX_SOURCE_CHARS
    if len(text) <= limit:
        return text
    return (
        f"{text[:limit]}\n\n[Source truncated for this prompt: showing the first {limit:,} of {len(text):,} "
        "characters. The full source is stored and its most relevant passages are provided as retrieved excerpts.]"
    )


async def get_project_source_text(db: AsyncSession, project: Project) -> str:
    """The text the AI stages treat as the project's source material."""
    sources = await get_project_source_texts(db, project)
    if len(sources) == 1:
        text = sources[0][1]
    elif sources:
        text = "\n\n".join(f"--- Source {i}: {name} ---\n{body}" for i, (name, body) in enumerate(sources, 1))
    else:
        # No ingested source (e.g. ingestion failed or a legacy project): fall back to project fields.
        text = project.description or project.source_reference or f"Project: {project.title}"
    return cap_for_prompt(text)
