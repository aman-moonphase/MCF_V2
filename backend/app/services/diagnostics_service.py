"""Read-only health overview for the Diagnostics page.

Rules:
- Read-only: only SELECTs against the database and reads of configuration / migration files. Nothing is written,
  generated, scheduled or published, and no provider object is created — so no AI or embedding call (paid or not).
- No secrets: never a database URL, key, token, password or raw driver error (only a generic message and the
  exception class name). Credentials are reported as a boolean, and a configured credential is never presented as a
  verified connection.
- Isolation: ingestion figures cover the signed-in user's own projects only.
- States: Healthy | Warning | Unavailable | Unknown | Not checked (a check that did not run because something it
  depends on failed is "Not checked", never "Unavailable"). "Not configured" / "Ready" / "Enabled" / "Degraded"
  remain for the existing fields.
"""

from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.config import ai_mode_summary, embedding_summary
from app.core.config import settings
from app.models.project import Project
from app.models.source import DocumentChunk, SourceDocument
from app.services.retrieval_service import is_stale, source_hashes

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI = BACKEND_DIR / "alembic.ini"
FAILED_SOURCE_LIMIT = 5


def _generic_failure(what: str, exc: Exception) -> str:
    # Never include str(exc): driver errors can contain hosts, users or connection details.
    return f"{what} failed ({type(exc).__name__})."


def _scripts():
    """The migration scripts shipped with this code (files only; env.py is not run, the database is not touched)."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    return ScriptDirectory.from_config(config)


def migration_heads() -> Tuple[str, ...]:
    """Head revision(s) of the migration scripts shipped with this code."""
    return tuple(_scripts().get_heads())


def migration_revision_known(revision: str) -> bool:
    script = _scripts()
    try:
        return script.get_revision(revision) is not None
    except Exception:
        return False


async def _current_revisions(db: AsyncSession) -> Optional[List[str]]:
    """Revisions recorded in alembic_version, or None when the table does not exist."""
    exists = (await db.execute(text("SELECT to_regclass('alembic_version') IS NOT NULL"))).scalar()
    if not exists:
        return None
    return list((await db.execute(text("SELECT version_num FROM alembic_version"))).scalars().all())


async def _migration(db: AsyncSession, db_ok: bool) -> Dict[str, Any]:
    if not db_ok:
        return {"status": "Not checked", "current_revision": None, "head_revision": None,
                "message": "Not checked because the database is unavailable."}
    try:
        heads = migration_heads()
    except Exception as exc:
        return {"status": "Unknown", "current_revision": None, "head_revision": None,
                "message": _generic_failure("Reading the migration scripts", exc)}
    head = heads[0] if len(heads) == 1 else None
    try:
        current = await _current_revisions(db)
    except Exception as exc:
        return {"status": "Unknown", "current_revision": None, "head_revision": head,
                "message": _generic_failure("Reading the database migration revision", exc)}
    if current is None or not current:
        return {"status": "Unknown", "current_revision": None, "head_revision": head,
                "message": "This database has no migration record, so its schema version cannot be confirmed."}
    revision = current[0] if len(current) == 1 else ", ".join(sorted(current))
    if len(heads) != 1:
        return {"status": "Warning", "current_revision": revision, "head_revision": ", ".join(heads),
                "message": "The migration scripts have more than one head; the expected schema is ambiguous."}
    if current == [head]:
        return {"status": "Healthy", "current_revision": revision, "head_revision": head,
                "message": "The database schema is up to date."}
    if len(current) == 1 and migration_revision_known(current[0]):
        return {"status": "Warning", "current_revision": revision, "head_revision": head,
                "message": "The database schema is behind the code. Apply the pending migrations (alembic upgrade head)."}
    return {"status": "Warning", "current_revision": revision, "head_revision": head,
            "message": "The database is at a revision this code does not know (it may be newer than the code)."}


async def _ingestion(db: AsyncSession, db_ok: bool, user_id: int, embedding: Dict[str, Any]) -> Dict[str, Any]:
    empty = {"sources_total": 0, "sources_by_status": {}, "chunks_total": 0, "stale_chunks": 0,
             "other_embedding_chunks": 0, "failed_sources": []}
    if not db_ok:
        return {**empty, "status": "Not checked", "message": "Not checked because the database is unavailable."}
    try:
        own = select(Project.id).where(Project.user_id == user_id).scalar_subquery()
        by_status = dict((await db.execute(
            select(SourceDocument.status, func.count()).where(SourceDocument.project_id.in_(own))
            .group_by(SourceDocument.status))).all())
        docs = (await db.execute(
            select(SourceDocument.id, SourceDocument.metadata_, SourceDocument.extracted_text)
            .where(SourceDocument.project_id.in_(own), SourceDocument.status == "completed"))).all()
        source_hash = DocumentChunk.metadata_["source_content_hash"].astext
        provider = DocumentChunk.metadata_["embedding_provider"].astext
        model = DocumentChunk.metadata_["embedding_model"].astext
        groups = (await db.execute(
            select(DocumentChunk.source_document_id, source_hash, provider, model, func.count())
            .where(DocumentChunk.project_id.in_(own))
            .group_by(DocumentChunk.source_document_id, source_hash, provider, model))).all()
        failed = (await db.execute(
            select(SourceDocument.name, SourceDocument.updated_at).where(
                SourceDocument.project_id.in_(own), SourceDocument.status == "failed")
            .order_by(SourceDocument.updated_at.desc().nulls_last()).limit(FAILED_SOURCE_LIMIT))).all()
    except Exception as exc:
        return {**empty, "status": "Unknown", "message": _generic_failure("Reading source indexing data", exc)}

    current_hashes = {doc_id: source_hashes(SimpleNamespace(metadata_=meta, extracted_text=body))
                      for doc_id, meta, body in docs}
    chunks_total = stale = other_embedding = 0
    for doc_id, recorded, chunk_provider, chunk_model, count in groups:
        chunks_total += count
        if doc_id in current_hashes and is_stale({"source_content_hash": recorded}, current_hashes[doc_id]):
            stale += count
        if (chunk_provider, chunk_model) != (embedding["provider"], embedding["model"]):
            other_embedding += count
    failed_count = by_status.get("failed", 0)
    result = {
        "sources_total": sum(by_status.values()), "sources_by_status": by_status, "chunks_total": chunks_total,
        "stale_chunks": stale, "other_embedding_chunks": other_embedding,
        "failed_sources": [{"name": name, "updated_at": updated} for name, updated in failed],
    }
    problems = []
    if stale:
        problems.append(f"{stale} chunk(s) are out of date with their source text and are skipped until the source is re-indexed")
    if failed_count:
        problems.append(f"{failed_count} source(s) failed to ingest")
    if result["sources_total"] == 0:
        return {**result, "status": "Healthy", "message": "You have no ingested sources yet."}
    if problems:
        return {**result, "status": "Warning", "message": "; ".join(problems).capitalize() + "."}
    note = (f" {other_embedding} chunk(s) were indexed before embedding details were recorded, or with another "
            "provider/model; they are ranked by keyword relevance (re-index a source to refresh it).") if other_embedding else ""
    return {**result, "status": "Healthy", "message": f"Your sources are indexed and current.{note}"}


def _overall(sections: List[str]) -> Dict[str, str]:
    if "Unavailable" in sections:
        return {"status": "Unavailable", "message": "At least one required service is unavailable."}
    if "Warning" in sections or "Degraded" in sections or "Not configured" in sections:
        return {"status": "Warning", "message": "The application works, but some checks need attention."}
    if "Unknown" in sections or "Not checked" in sections:
        return {"status": "Unknown", "message": "Some checks could not be completed."}
    return {"status": "Healthy", "message": "All checks passed."}


async def collect_diagnostics(db: AsyncSession, user_id: int) -> Dict[str, Any]:
    checked_at = datetime.now(timezone.utc)

    # Database connectivity (everything that reads the database depends on it).
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
        database = {"status": "Healthy", "message": "Database connection successful."}
    except Exception as exc:
        db_ok = False
        database = {"status": "Unavailable", "message": _generic_failure("Connecting to the database", exc)}

    if not db_ok:
        vector_store = {"status": "Not checked", "extension": None, "message": "Not checked because the database is unavailable."}
    else:
        try:
            ext = (await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))).scalar_one_or_none()
            vector_store = ({"status": "Enabled", "extension": "pgvector", "message": "Vector extension is active."} if ext
                            else {"status": "Not configured", "extension": None,
                                  "message": "The pgvector extension is not installed in the database."})
        except Exception as exc:
            vector_store = {"status": "Unknown", "extension": None, "message": _generic_failure("Checking the vector extension", exc)}

    migration = await _migration(db, db_ok)

    # AI: configuration only. "Ready" keeps its existing meaning — configured and usable — and is never a claim that
    # the connection works: `connection_verified` is always False and the message says so.
    mode = ai_mode_summary()
    if mode["mode"] == "demo":
        ai_status, ai_message, ai_model = "Ready", "Demo Mode: deterministic output; no external AI calls and no charges.", "Deterministic demo (no model)"
    elif not mode["configured"]:
        ai_status, ai_message, ai_model = "Not configured", mode["configuration_problem"], mode["model"] or "—"
    else:
        ai_status, ai_model = "Ready", mode["model"] or "—"
        ai_message = ("Configured; credentials are set. The connection is not tested here (diagnostics never make "
                      "paid calls), so it is not verified.")
    ai = {"status": ai_status, "provider": mode["provider"], "model": ai_model, "message": ai_message,
          "mode": mode["mode"], "credentials_configured": mode["credentials_configured"],
          "connection_verified": False, "may_incur_charges": mode["may_incur_charges"],
          "single_attempt": mode["single_attempt"]}

    emb = embedding_summary()
    if emb["problem"]:
        emb_status, emb_message = "Not configured", emb["problem"]
    elif emb["provider"] == "demo":
        emb_status, emb_message = "Ready", ("Demo embeddings (free, offline). They carry no meaning, so retrieval "
                                            "ranks excerpts by keyword relevance, not semantic similarity.")
    else:
        emb_status, emb_message = "Ready", ("Configured; credentials are set. The embedding connection is not tested "
                                            "here, so it is not verified.")
    embeddings = {"status": emb_status, "provider": emb["provider"], "message": emb_message, "model": emb["model"],
                  "semantic": emb["semantic"], "credentials_configured": emb["credentials_configured"]}

    if not db_ok:
        rag = {"status": "Not checked", "message": "Not checked because the database is unavailable."}
    elif vector_store["status"] != "Enabled":
        rag = {"status": "Unavailable", "message": "Retrieval is unavailable because the vector store is not enabled."}
    elif emb_status == "Not configured":
        rag = {"status": "Degraded", "message": "Retrieval may be degraded: the embedding provider is not configured."}
    else:
        rag = {"status": "Ready", "message": ("Retrieval is available (keyword relevance)." if not emb["semantic"]
                                             else "Retrieval is available (keyword + semantic relevance).")}

    ingestion = await _ingestion(db, db_ok, user_id, emb)

    # Same rule as before (the database URL is only inspected here, never returned).
    if mode["mode"] == "demo":
        env_mode = "Demo"
    elif "localhost" not in settings.DATABASE_URL and "127.0.0.1" not in settings.DATABASE_URL:
        env_mode = "Production"
    else:
        env_mode = "Development"
    environment = {"mode": env_mode, "message": "Configuration is loaded from the server environment; no values are shown."}

    overall = _overall([database["status"], vector_store["status"], migration["status"], ai_status, emb_status,
                        rag["status"], ingestion["status"]])
    return {"checked_at": checked_at, "overall": overall, "backend": {"status": "Healthy", "message": "API is reachable."},
            "database": database, "vector_store": vector_store, "migration": migration, "ai": ai,
            "embeddings": embeddings, "rag": rag, "ingestion": ingestion, "environment": environment}
