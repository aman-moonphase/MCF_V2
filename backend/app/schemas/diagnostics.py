from datetime import datetime
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# "Not checked": the check did not run because something it depends on failed (it did not fail itself).
DiagnosticStatus = Literal["Healthy", "Warning", "Degraded", "Unavailable", "Unknown", "Not checked", "Not configured",
                           "Ready", "Enabled"]


class OverallDiagnostic(BaseModel):
    status: DiagnosticStatus
    message: str | None = None


class BackendDiagnostic(BaseModel):
    status: DiagnosticStatus
    message: str | None = None


class DatabaseDiagnostic(BaseModel):
    status: DiagnosticStatus
    message: str | None = None


class VectorStoreDiagnostic(BaseModel):
    status: DiagnosticStatus
    extension: str | None = None
    message: str | None = None


class MigrationDiagnostic(BaseModel):
    status: DiagnosticStatus
    current_revision: str | None = None
    head_revision: str | None = None
    message: str | None = None


class AIDiagnostic(BaseModel):
    status: DiagnosticStatus
    provider: str
    model: str
    message: str | None = None
    mode: Literal["demo", "real"] = "demo"
    # A boolean only — never the value or a fragment of it.
    credentials_configured: bool = False
    # Always False: diagnostics never call the provider, so a connection is never verified here.
    connection_verified: bool = False
    may_incur_charges: bool = False
    single_attempt: bool = False


class EmbeddingDiagnostic(BaseModel):
    status: DiagnosticStatus
    provider: str
    message: str | None = None
    model: str | None = None
    semantic: bool = False
    credentials_configured: bool = False


class RAGDiagnostic(BaseModel):
    status: DiagnosticStatus
    message: str | None = None


class FailedSource(BaseModel):
    name: str
    updated_at: Optional[datetime] = None


class IngestionDiagnostic(BaseModel):
    """The signed-in user's own sources only."""
    status: DiagnosticStatus
    message: str | None = None
    sources_total: int = 0
    sources_by_status: Dict[str, int] = Field(default_factory=dict)
    chunks_total: int = 0
    stale_chunks: int = 0
    other_embedding_chunks: int = 0
    failed_sources: List[FailedSource] = Field(default_factory=list)


class EnvironmentDiagnostic(BaseModel):
    mode: str
    message: str | None = None


class DiagnosticsResponse(BaseModel):
    checked_at: datetime | None = None
    overall: OverallDiagnostic | None = None
    backend: BackendDiagnostic
    database: DatabaseDiagnostic
    vector_store: VectorStoreDiagnostic
    migration: MigrationDiagnostic | None = None
    ai: AIDiagnostic
    embeddings: EmbeddingDiagnostic
    rag: RAGDiagnostic
    ingestion: IngestionDiagnostic | None = None
    environment: EnvironmentDiagnostic
