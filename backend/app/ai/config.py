from pydantic import BaseModel

SUPPORTED_AI_PROVIDERS = ("demo", "openai", "claude")


class AIConfig(BaseModel):
    provider: str
    api_key: str | None = None
    model_name: str = "gpt-4o-mini"
    temperature: float = 0.7
    timeout: float = 120.0
    max_tokens: int | None = None
    effort: str | None = None


def claude_model_problem(model_name: str | None) -> str | None:
    """Why a CLAUDE_MODEL value cannot be sent, or None. The ID is never rewritten or replaced: an
    unknown-but-well-formed ID goes to the API, which reports it (see ClaudeProvider NotFound handling)."""
    if model_name is None or not model_name.strip():
        return "CLAUDE_MODEL is empty. Set it to a Claude API model ID such as 'claude-sonnet-5-5'."
    if model_name != model_name.strip() or any(c.isspace() for c in model_name):
        return f"CLAUDE_MODEL {model_name!r} contains spaces. Use the exact Claude API model ID, e.g. 'claude-sonnet-5-5'."
    return None


def normalize_provider_name(provider: str | None) -> str:
    name = (provider or "").strip().lower()
    # "anthropic" is accepted as an alias of "claude".
    return "claude" if name == "anthropic" else name


def build_ai_config() -> AIConfig:
    """Build the AI configuration for the configured provider from environment settings.

    Only the selected provider's key is placed in the config, and it never leaves the backend.
    """
    from ..core.config import settings

    provider = normalize_provider_name(settings.AI_PROVIDER)
    if provider == "claude":
        return AIConfig(
            provider=provider,
            api_key=settings.ANTHROPIC_API_KEY,
            model_name=settings.CLAUDE_MODEL,
            temperature=settings.AI_TEMPERATURE,
            timeout=settings.AI_TIMEOUT_SECONDS,
            max_tokens=settings.CLAUDE_MAX_TOKENS,
            effort=settings.CLAUDE_EFFORT,
        )
    if provider == "openai":
        return AIConfig(
            provider=provider,
            api_key=settings.OPENAI_API_KEY,
            model_name=settings.AI_MODEL_NAME,
            temperature=settings.AI_TEMPERATURE,
            timeout=settings.AI_TIMEOUT_SECONDS,
        )
    return AIConfig(
        provider=provider,
        model_name=settings.AI_MODEL_NAME,
        temperature=settings.AI_TEMPERATURE,
        timeout=settings.AI_TIMEOUT_SECONDS,
    )


def build_embedding_config() -> AIConfig:
    """Embedding config: the embedding provider is chosen independently of the chat provider,
    because Claude has no embeddings endpoint."""
    from ..core.config import settings

    provider = settings.resolved_embedding_provider
    return AIConfig(
        provider=provider,
        api_key=settings.OPENAI_API_KEY if provider == "openai" else None,
        model_name=settings.AI_MODEL_NAME,
        temperature=settings.AI_TEMPERATURE,
        timeout=settings.AI_TIMEOUT_SECONDS,
    )
