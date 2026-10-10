"""Splits extracted source text into bounded, overlapping chunks with provenance.

- Boundaries prefer paragraphs, then lines, then sentence ends, then words (separators stay at the chunk's end).
- Each chunk records where it came from: character range in the full extracted text, the PDF page (when the
  extractor reported page ranges), and a content hash. Chunks never carry the source's raw text or server paths.
"""

import hashlib
from bisect import bisect_right
from typing import Any, Dict, List, Optional, Sequence

from langchain_text_splitters import RecursiveCharacterTextSplitter

# Source metadata fields that may be copied onto chunks (never raw_text, file paths, or errors).
CHUNK_METADATA_FIELDS = ("title", "source_url", "source_type", "original_filename")


def content_hash(text: str) -> str:
    """Stable fingerprint of text, ignoring whitespace differences."""
    return hashlib.sha256(" ".join((text or "").split()).encode("utf-8")).hexdigest()


class ChunkResult:
    def __init__(self, content: str, chunk_index: int, metadata: Dict[str, Any]):
        self.content = content
        self.chunk_index = chunk_index
        self.metadata = metadata
        self.token_count = len(content.split())  # approximate


class ChunkingService:
    @staticmethod
    def chunk_text(text: str, base_metadata: Optional[Dict[str, Any]] = None, chunk_size: Optional[int] = None,
                   chunk_overlap: Optional[int] = None, page_ranges: Optional[Sequence[Sequence[int]]] = None,
                   page_numbers: Optional[Sequence[int]] = None) -> List[ChunkResult]:
        """`page_ranges`: [[start, end], ...] character offsets of the PDF pages in `text`; `page_numbers`: the
        page number of each range (pages without text are skipped, so position is not the page number)."""
        from app.core.config import settings

        if not text or not text.strip():
            return []
        size = chunk_size or settings.RAG_CHUNK_SIZE
        overlap = min(chunk_overlap if chunk_overlap is not None else settings.RAG_CHUNK_OVERLAP, size // 2)
        splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, add_start_index=True,
                                                  separators=["\n\n", "\n", ". ", " ", ""], keep_separator="end")
        base = {k: v for k, v in (base_metadata or {}).items() if k in CHUNK_METADATA_FIELDS and v}
        page_starts = [int(r[0]) for r in page_ranges] if page_ranges else []

        results: List[ChunkResult] = []
        for doc in splitter.create_documents([text]):
            content = doc.page_content.strip()
            if not content:
                continue
            start = int(doc.metadata.get("start_index", -1))
            meta = {**base, "chunk_index": len(results), "char_start": start,
                    "char_end": start + len(doc.page_content) if start >= 0 else None, "content_hash": content_hash(content)}
            if page_starts and start >= 0:
                index = max(0, bisect_right(page_starts, start) - 1)
                meta["page"] = int(page_numbers[index]) if page_numbers and index < len(page_numbers) else index + 1
            results.append(ChunkResult(content=content, chunk_index=len(results), metadata=meta))
        return results
