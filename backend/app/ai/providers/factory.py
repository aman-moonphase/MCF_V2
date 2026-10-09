from .base import BaseAIProvider
from .demo_provider import DemoProvider
from .openai_provider import OpenAIProvider
from ..config import AIConfig, SUPPORTED_AI_PROVIDERS, build_ai_config, normalize_provider_name


class AIProviderFactory:
    @staticmethod
    def get_provider(config: AIConfig) -> BaseAIProvider:
        provider = normalize_provider_name(config.provider)

        if provider == "demo":
            return DemoProvider()

        if provider == "openai":
            if not config.api_key:
                raise ValueError("OPENAI_API_KEY is required when using the 'openai' provider.")
            return OpenAIProvider(
                model_name=config.model_name,
                temperature=config.temperature,
                api_key=config.api_key,
                timeout=config.timeout,
            )

        if provider == "claude":
            if not config.api_key:
                raise ValueError("ANTHROPIC_API_KEY is required when using the 'claude' provider.")
            from .claude_provider import ClaudeProvider

            return ClaudeProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                max_tokens=config.max_tokens or 16000,
                effort=config.effort,
                timeout=config.timeout,
            )

        # No silent fallback: a misconfigured provider must fail loudly instead of quietly
        # serving demo output as if it came from a real model.
        raise ValueError(
            f"Unsupported AI_PROVIDER '{config.provider}'. Supported values: {', '.join(SUPPORTED_AI_PROVIDERS)}."
        )


def get_configured_provider() -> BaseAIProvider:
    """The provider selected by environment settings. All workflow nodes resolve providers here."""
    return AIProviderFactory.get_provider(build_ai_config())
