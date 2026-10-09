from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.db.session import get_db
from app.core.config import settings
from app.ai.config import SUPPORTED_AI_PROVIDERS, normalize_provider_name
from app.schemas.diagnostics import (
    DiagnosticsResponse, 
    BackendDiagnostic, 
    DatabaseDiagnostic, 
    VectorStoreDiagnostic,
    AIDiagnostic,
    EmbeddingDiagnostic,
    RAGDiagnostic,
    EnvironmentDiagnostic
)
from app.api.deps import get_current_user
from app.models.user import User

router = APIRouter()

@router.get("", response_model=DiagnosticsResponse)
async def get_diagnostics(db: AsyncSession = Depends(get_db), current_user: User = Depends(get_current_user)):
    # 1. Backend Status
    backend = BackendDiagnostic(status="Healthy", message="API is reachable")

    # 2. Database Status
    db_status = "Unavailable"
    db_msg = "Could not connect to database"
    try:
        await db.execute(text("SELECT 1"))
        db_status = "Healthy"
        db_msg = "Database connection successful"
    except Exception as e:
        db_msg = f"Database error: {str(e)}"
    
    database = DatabaseDiagnostic(status=db_status, message=db_msg)

    # 3. Vector Store Status
    vs_status = "Unavailable"
    vs_ext = None
    vs_msg = "pgvector extension check failed"
    if db_status == "Healthy":
        try:
            result = await db.execute(text("SELECT extname FROM pg_extension WHERE extname = 'vector'"))
            ext = result.scalar_one_or_none()
            if ext:
                vs_status = "Enabled"
                vs_ext = "pgvector"
                vs_msg = "Vector extension is active"
            else:
                vs_status = "Not configured"
                vs_msg = "pgvector extension is not installed in the database"
        except Exception as e:
            vs_msg = f"Vector check error: {str(e)}"
    
    vector_store = VectorStoreDiagnostic(status=vs_status, extension=vs_ext, message=vs_msg)

    # 4. AI Provider
    # Mask API keys, never expose them!
    ai_status = "Ready"
    ai_msg = "AI Provider configured successfully"
    provider = normalize_provider_name(settings.AI_PROVIDER)
    model = settings.AI_MODEL_NAME
    if provider not in SUPPORTED_AI_PROVIDERS:
        ai_status = "Not configured"
        ai_msg = f"Unsupported AI provider. Use one of: {', '.join(SUPPORTED_AI_PROVIDERS)}"
    elif provider == "openai" and not (settings.OPENAI_API_KEY or "").strip():
        ai_status = "Not configured"
        ai_msg = "OpenAI API Key is missing for production AI Provider"
    elif provider == "claude":
        model = settings.CLAUDE_MODEL
        if not (settings.ANTHROPIC_API_KEY or "").strip():
            ai_status = "Not configured"
            ai_msg = "Anthropic API Key is missing for the Claude provider"
    elif provider == "demo":
        model = "Deterministic demo (no model)"

    ai = AIDiagnostic(
        status=ai_status,
        provider=provider,
        model=model,
        message=ai_msg
    )

    # 5. Embedding Provider (chosen independently; Claude has no embeddings API)
    embedding_provider = settings.resolved_embedding_provider
    emb_status = "Ready"
    emb_msg = "Embeddings configured successfully"
    if embedding_provider.lower() != "demo":
        if not settings.OPENAI_API_KEY or settings.OPENAI_API_KEY.strip() == "":
            emb_status = "Not configured"
            emb_msg = "OpenAI API Key is missing for embeddings"

    embeddings = EmbeddingDiagnostic(
        status=emb_status,
        provider=embedding_provider,
        message=emb_msg
    )

    # 6. RAG Diagnostic
    rag_status = "Ready"
    rag_msg = "RAG components are available"
    if vs_status != "Enabled":
        rag_status = "Unavailable"
        rag_msg = "RAG is unavailable because Vector Store is not enabled"
    elif emb_status != "Ready":
        rag_status = "Degraded"
        rag_msg = "RAG might be degraded due to missing embedding configuration"

    rag = RAGDiagnostic(status=rag_status, message=rag_msg)

    # 7. Environment
    # We check if we are in demo mode. 
    # If the database URL contains localhost or we're explicitly running demo, we call it Development or Demo.
    env_mode = "Development"
    if settings.AI_PROVIDER.lower() == "demo":
        env_mode = "Demo"
    elif "localhost" not in settings.DATABASE_URL and "127.0.0.1" not in settings.DATABASE_URL:
        env_mode = "Production"

    environment = EnvironmentDiagnostic(
        mode=env_mode,
        message="Environment variables loaded safely"
    )

    return DiagnosticsResponse(
        backend=backend,
        database=database,
        vector_store=vector_store,
        ai=ai,
        embeddings=embeddings,
        rag=rag,
        environment=environment
    )
