"""Retrieval over indexed source chunks (pgvector + keyword relevance), with ownership and provenance.

- Scope and ownership are applied in the SQL query itself: only chunks of the given project(s) that belong to the
  given user can be returned — before anything can reach a prompt.
- Failed / duplicate sources are excluded. A chunk whose recorded source hash no longer matches its source (the
  source's recorded hash or the hash of its current extracted text) is stale and skipped (counted, never used).
- Relevance: keyword coverage (IDF-weighted) of the query, combined with vector similarity only when the embedding
  provider is semantic AND the chunk was embedded by the same provider/model. Demo embeddings carry no meaning,
  so Demo Mode ranks by keywords; legacy chunks without provenance are ranked by keywords only.
- Results below the relevance threshold are dropped — an empty result is reported as such, never padded.
- Diversity: at most N excerpts per source document, no near-identical excerpts.
- Each excerpt has a stable reference ("S:<source-id-8>#<chunk-index>") and its source metadata.
"""

import math
import re
import uuid
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import AIConfig
from app.ai.providers.embedding.factory import EmbeddingProviderFactory
from app.models.project import Project
from app.models.source import DocumentChunk, SourceDocument
from app.services.chunking_service import content_hash

_EXCLUDED_STATUSES = ("failed", "duplicate")
_STOP = {"the", "and", "for", "with", "that", "this", "from", "your", "you", "are", "was", "what", "which", "who",
         "how", "its", "our", "has", "have", "into", "any", "all", "can", "not", "but", "about", "they", "them",
         "their", "will", "does", "did", "when", "where", "there", "these", "those", "than", "then", "also"}


def excerpt_ref(source_document_id, chunk_index: int) -> str:
    """Stable evidence reference for a chunk: same source + chunk → same label across runs."""
    return f"S:{str(source_document_id).replace('-', '')[:8]}#{chunk_index}"


def source_hashes(doc: SourceDocument) -> set:
    """What the source holds NOW: its recorded hash and the hash of its current extracted text. A chunk is stale
    when the source hash it was indexed from is not among them (e.g. the text changed and was not re-indexed)."""
    hashes = {(doc.metadata_ or {}).get("content_hash")}
    if doc.extracted_text:
        hashes.add(content_hash(doc.extracted_text))
    return {h for h in hashes if h}


def is_stale(chunk_meta: dict, current_hashes: set) -> bool:
    recorded = (chunk_meta or {}).get("source_content_hash")
    return bool(recorded and current_hashes and any(h != recorded for h in current_hashes))


def _terms(text: str) -> List[str]:
    return [w[:6] for w in re.findall(r"[a-z0-9][a-z0-9-]{2,}", (text or "").lower()) if w not in _STOP]


class RetrievedChunk:
    """One retrieved excerpt. `score` is the combined relevance (0-1)."""

    def __init__(self, content: str, score: float, source_document_id: str, chunk_id: str, metadata: dict,
                 ref: str = "", source_name: str = "", chunk_index: int = 0, lexical: float = 0.0,
                 semantic: Optional[float] = None):
        self.content = content
        self.score = score
        self.source_document_id = source_document_id
        self.chunk_id = chunk_id
        self.metadata = metadata
        self.ref = ref
        self.source_name = source_name
        self.chunk_index = chunk_index
        self.lexical = lexical
        self.semantic = semantic

    @property
    def page(self) -> Optional[int]:
        return (self.metadata or {}).get("page")

    def describe(self) -> str:
        where = f"{self.source_name or 'source'}, excerpt {self.chunk_index + 1}" + (f", page {self.page}" if self.page else "")
        return f"Source excerpt ({where}) — unverified source text"


@dataclass
class RetrievalResult:
    status: str  # ok | no_sources | no_relevant_results
    chunks: List[RetrievedChunk] = field(default_factory=list)
    considered: int = 0
    skipped_stale: int = 0
    keyword_only: int = 0  # chunks ranked without vectors (non-semantic provider, legacy or other-provider vectors)
    mode: str = "keyword"  # keyword | hybrid

    def note(self) -> str:
        if self.status == "no_sources":
            return "No indexed source excerpts are available."
        if self.status == "no_relevant_results":
            return "No source excerpt was relevant enough to include; nothing was substituted."
        extra = f" {self.skipped_stale} outdated chunk(s) were skipped (re-index the source)." if self.skipped_stale else ""
        return f"{len(self.chunks)} relevant excerpt(s) from {self.considered} indexed chunk(s), ranked by {self.mode} relevance.{extra}"


class RetrievalService:
    @staticmethod
    async def retrieve_evidence(
        db: AsyncSession, query: str, config: AIConfig, *, user_id: Optional[int], project_ids: Sequence[uuid.UUID],
        top_k: int = 5, min_score: Optional[float] = None, max_per_source: Optional[int] = None,
    ) -> RetrievalResult:
        from app.core.config import settings

        threshold = settings.RAG_MIN_RELEVANCE if min_score is None else min_score
        per_source = max_per_source or settings.RAG_MAX_PER_SOURCE
        if not query or not query.strip() or not project_ids:
            return RetrievalResult(status="no_sources")

        provider = EmbeddingProviderFactory.get_provider(config)
        query_vector = await provider.embed_text(query) if provider.semantic else None

        stmt = (select(DocumentChunk, SourceDocument)
                .join(SourceDocument, SourceDocument.id == DocumentChunk.source_document_id)
                .join(Project, Project.id == DocumentChunk.project_id)
                .where(DocumentChunk.project_id.in_(list(project_ids)),
                       SourceDocument.project_id == DocumentChunk.project_id,
                       SourceDocument.status.notin_(_EXCLUDED_STATUSES)))
        if user_id is not None:
            stmt = stmt.where(Project.user_id == user_id)  # ownership enforced in the query itself
        if query_vector is not None:
            distance = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
            stmt = stmt.add_columns(distance).order_by(distance)
        else:
            stmt = stmt.order_by(DocumentChunk.project_id, DocumentChunk.source_document_id, DocumentChunk.chunk_index)
        rows = (await db.execute(stmt.limit(settings.RAG_CANDIDATE_LIMIT))).all()
        if not rows:
            return RetrievalResult(status="no_sources")

        result = RetrievalResult(status="no_relevant_results", mode="hybrid" if query_vector is not None else "keyword")
        candidates, hashes = [], {}
        for row in rows:
            chunk, doc = row[0], row[1]
            meta = chunk.metadata_ or {}
            if doc.id not in hashes:
                hashes[doc.id] = source_hashes(doc)
            if is_stale(meta, hashes[doc.id]):
                result.skipped_stale += 1
                continue
            same_vectors = (meta.get("embedding_provider") == provider.provider_name
                            and meta.get("embedding_model") == provider.model_name)
            semantic = None
            if query_vector is not None and same_vectors and len(row) > 2 and row[2] is not None:
                semantic = max(0.0, 1.0 - float(row[2]))
            else:
                result.keyword_only += 1
            candidates.append((chunk, doc, semantic))
        result.considered = len(candidates)

        query_terms = list(dict.fromkeys(_terms(query)))
        chunk_terms = [set(_terms(c.content)) for c, _, _ in candidates]
        n = max(1, len(candidates))
        idf = {t: math.log(1 + n / (1 + sum(t in terms for terms in chunk_terms))) for t in query_terms}
        total = sum(idf.values()) or 1.0

        scored = []
        for (chunk, doc, semantic), terms in zip(candidates, chunk_terms):
            lexical = sum(idf[t] for t in query_terms if t in terms) / total
            score = lexical if semantic is None else 0.6 * lexical + 0.4 * semantic
            if score >= threshold:
                scored.append((score, lexical, semantic, chunk, doc))
        scored.sort(key=lambda s: (-s[0], str(s[4].id), s[3].chunk_index))

        per_doc: Dict[str, int] = {}
        seen = set()
        for score, lexical, semantic, chunk, doc in scored:
            fingerprint = (chunk.metadata_ or {}).get("content_hash") or " ".join(chunk.content.split()).lower()
            if fingerprint in seen or per_doc.get(str(doc.id), 0) >= per_source:
                continue
            seen.add(fingerprint)
            per_doc[str(doc.id)] = per_doc.get(str(doc.id), 0) + 1
            result.chunks.append(RetrievedChunk(
                content=chunk.content, score=round(score, 4), source_document_id=str(doc.id), chunk_id=str(chunk.id),
                metadata={k: v for k, v in (chunk.metadata_ or {}).items() if k != "raw_text"},
                ref=excerpt_ref(doc.id, chunk.chunk_index), source_name=doc.name, chunk_index=chunk.chunk_index,
                lexical=round(lexical, 4), semantic=None if semantic is None else round(semantic, 4)))
            if len(result.chunks) >= top_k:
                break
        if result.chunks:
            result.status = "ok"
        return result

    @staticmethod
    async def retrieve(db: AsyncSession, project_id: uuid.UUID, query: str, config: AIConfig, top_k: int = 5,
                       user_id: Optional[int] = None) -> List[RetrievedChunk]:
        """Backwards-compatible: relevant excerpts of one project (empty when nothing is relevant)."""
        result = await RetrievalService.retrieve_evidence(db, query, config, user_id=user_id, project_ids=[project_id], top_k=top_k)
        return result.chunks

    @staticmethod
    async def product_project_ids(db: AsyncSession, product_id: uuid.UUID, user_id: int) -> List[uuid.UUID]:
        """Projects of a product that the user owns (the product-wide retrieval scope)."""
        rows = (await db.execute(select(Project.id).where(Project.product_id == product_id, Project.user_id == user_id))).scalars().all()
        return list(rows)


def format_excerpts(chunks: Iterable[RetrievedChunk], heading_note: str = "") -> str:
    """Prompt text for retrieved excerpts: each labelled with its stable reference and marked unverified."""
    parts = [f"[{c.ref}] {c.describe()}\n{c.content}" for c in chunks]
    return (heading_note + "\n\n" if heading_note else "") + "\n\n---\n\n".join(parts)


async def product_background(db: AsyncSession, product, user_id: int, profile: dict, config: AIConfig, top_k: int = 4):
    """(prompt_section or None, refs) — relevant excerpts from the sources of the product's own projects (owner
    only), for background in product-level steps. They are labelled unverified and are NOT added to the step's
    citable references: product facts must still cite the approved profile."""
    query = " ".join(filter(None, [profile.get("value_proposition"), profile.get("problem_solved"),
                                   " ".join(profile.get("differentiators") or []), " ".join(profile.get("key_features") or [])]))
    project_ids = await RetrievalService.product_project_ids(db, product.id, user_id)
    try:
        async with db.begin_nested():
            # A long multi-topic query (value proposition, problem, differentiators, features): lower threshold.
            result = await RetrievalService.retrieve_evidence(db, query, config, user_id=user_id, project_ids=project_ids,
                                                              top_k=top_k, min_score=0.1)
    except Exception:
        return None, []
    if not result.chunks:
        return ("Our own source excerpts", result.note()), []
    return (("Our own source excerpts — unverified background from our sources (not approved facts, not competitor "
             "evidence; do not cite these labels — cite profile:<field> for product facts)"),
            format_excerpts(result.chunks)), [c.ref for c in result.chunks]
