import logging
import secrets

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)

# The JWT secret that used to be hardcoded in this file. It is public (it lives in git history),
# so it must never be accepted as a real secret again.
_LEAKED_DEFAULT_SECRET_KEY = "09d25e094faa6ca2556c818166b7a9563b93f7099f6f0f4caa6cf63b88e8d3e7"
_DEVELOPMENT_ENVS = {"development", "dev", "local", "test", "demo"}
_MIN_SECRET_KEY_LENGTH = 32


# Default Claude model: the latest Sonnet listed in Anthropic's models overview (a documented Claude API ID).
DEFAULT_CLAUDE_MODEL = "claude-sonnet-5-5"


class Settings(BaseSettings):
    PROJECT_NAME: str = "Multimodal Content Factory API"
    API_V1_STR: str = "/api"

    # "development" | "test" | "demo" | "staging" | "production"
    ENV: str = "development"

    POSTGRES_USER: str | None = None
    POSTGRES_PASSWORD: str | None = None
    POSTGRES_DB: str | None = None
    DATABASE_URL: str

    @field_validator("DATABASE_URL")
    @classmethod
    def assemble_db_connection(cls, v: str) -> str:
        if v and v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v and v.startswith("postgresql://"):
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    FRONTEND_URL: str = "http://localhost:3000"

    # Security — SECRET_KEY must come from the environment. See _resolve_secret_key below.
    SECRET_KEY: str | None = None
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 8 # 8 days

    # AI Configuration
    # Supported providers: "demo" (default, no key needed), "openai", "claude".
    AI_PROVIDER: str = "demo"
    AI_TEMPERATURE: float = 0.7
    AI_TIMEOUT_SECONDS: float = 120.0
    # Single-attempt mode for controlled real-AI tests: no application-level generation retries and no SDK
    # retries, so one user action makes at most one provider request per AI step. Off = normal retries.
    AI_SINGLE_ATTEMPT: bool = False
    # Maximum characters of the project's source text placed directly in a prompt.
    # Longer sources are still fully stored and reachable through RAG; the prompt states the cut.
    AI_MAX_SOURCE_CHARS: int = 60000

    # OpenAI
    OPENAI_API_KEY: str | None = None
    AI_MODEL_NAME: str = "gpt-4o-mini"

    # Claude (Anthropic). The key is only ever read on the backend.
    ANTHROPIC_API_KEY: str | None = None
    # Claude API model ID, sent to the API exactly as written (no fallback). Default: DEFAULT_CLAUDE_MODEL.
    # Other documented IDs can be set explicitly, e.g. claude-opus-5-5, claude-opus-5, claude-sonnet-5.
    CLAUDE_MODEL: str = DEFAULT_CLAUDE_MODEL
    CLAUDE_MAX_TOKENS: int = 16000
    # Claude effort level: low | medium | high | xhigh | max
    CLAUDE_EFFORT: str = "medium"

    # Output policy for generated LinkedIn posts (app/ai/platform_policy.py)
    LINKEDIN_POST_MAX_CHARS: int = 3000
    LINKEDIN_HOOK_MAX_CHARS: int = 210

    # Embeddings: "demo" or "openai". Defaults to "openai" only when AI_PROVIDER is "openai".
    EMBEDDING_PROVIDER: str | None = None

    # URL ingestion safety (SSRF protection). Keep False outside local experiments.
    ALLOW_PRIVATE_URL_INGESTION: bool = False

    # Email
    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    SMTP_FROM_EMAIL: str | None = None

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def is_development(self) -> bool:
        return self.ENV.strip().lower() in _DEVELOPMENT_ENVS

    @property
    def resolved_embedding_provider(self) -> str:
        if self.EMBEDDING_PROVIDER:
            return self.EMBEDDING_PROVIDER.strip().lower()
        return "openai" if self.AI_PROVIDER.strip().lower() == "openai" else "demo"

    @model_validator(mode="after")
    def _resolve_secret_key(self) -> "Settings":
        key = (self.SECRET_KEY or "").strip()
        if key == _LEAKED_DEFAULT_SECRET_KEY:
            raise ValueError(
                "SECRET_KEY is set to the old hardcoded default, which is public. Generate a new one, "
                "e.g. python -c \"import secrets; print(secrets.token_urlsafe(64))\""
            )
        if key and len(key) < _MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"SECRET_KEY must be at least {_MIN_SECRET_KEY_LENGTH} characters long.")
        if not key:
            if not self.is_development:
                raise ValueError(
                    f"SECRET_KEY must be set via the environment when ENV='{self.ENV}'. "
                    "Refusing to start with an unset JWT secret."
                )
            # Development only: an ephemeral random key. Tokens are invalidated on every restart,
            # so set SECRET_KEY in backend/.env for a stable local session.
            key = secrets.token_urlsafe(64)
            logger.warning(
                "SECRET_KEY is not set; generated an ephemeral development key. "
                "Set SECRET_KEY in backend/.env to keep logins across restarts."
            )
        self.SECRET_KEY = key
        return self


settings = Settings()
