import os
from .base import BaseEmbeddingProvider
from .demo import DemoEmbeddingProvider
from .openai import OpenAIEmbeddingProvider
from app.ai.config import AIConfig


class EmbeddingProviderFactory:
    @staticmethod
    def get_provider(config: AIConfig) -> BaseEmbeddingProvider:
        # The embedding provider is chosen by config.provider (see app.ai.config.build_embedding_config,
        # driven by EMBEDDING_PROVIDER). Claude has no embeddings API, so it is not a valid choice here.
        embedding_provider = (config.provider or "").strip().lower()

        if embedding_provider == "openai":
            if not config.api_key:
                raise ValueError("OPENAI_API_KEY is required when using the 'openai' embedding provider.")
            # Use text-embedding-3-small as default for OpenAI
            model_name = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
            return OpenAIEmbeddingProvider(
                model_name=model_name,
                api_key=config.api_key
            )

        if embedding_provider == "demo":
            return DemoEmbeddingProvider()

        raise ValueError(
            f"Unsupported embedding provider '{config.provider}'. Set EMBEDDING_PROVIDER to 'demo' or 'openai'."
        )
