from .base import BaseAIProvider
from .demo_provider import DemoProvider
from .openai_provider import OpenAIProvider
from ..nodes.common import sdk_max_retries
from ..config import AIConfig, SUPPORTED_AI_PROVIDERS, build_ai_config, claude_model_problem, normalize_provider_name


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
            problem = claude_model_problem(config.model_name)
            if problem:
                raise ValueError(problem)
            from .claude_provider import ClaudeProvider

            return ClaudeProvider(
                api_key=config.api_key,
                model_name=config.model_name,
                max_tokens=config.max_tokens or 16000,
                effort=config.effort,
                timeout=config.timeout,
                max_retries=sdk_max_retries(),
            )

        # No silent fallback: a misconfigured provider must fail loudly instead of quietly
        # serving demo output as if it came from a real model.
        raise ValueError(
            f"Unsupported AI_PROVIDER '{config.provider}'. Supported values: {', '.join(SUPPORTED_AI_PROVIDERS)}."
        )


def get_configured_provider() -> BaseAIProvider:
    """The provider selected by environment settings. All workflow nodes resolve providers here."""
    return AIProviderFactory.get_provider(build_ai_config())
