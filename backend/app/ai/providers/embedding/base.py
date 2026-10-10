from abc import ABC, abstractmethod
from typing import List

class BaseEmbeddingProvider(ABC):
    # Recorded on every indexed chunk, so vectors from different providers/models are never compared.
    provider_name: str = "unknown"
    model_name: str = "unknown"
    # True when vector similarity reflects meaning. Retrieval only uses vector scores from semantic providers.
    semantic: bool = True

    @abstractmethod
    async def embed_text(self, text: str) -> List[float]:
        """Embed a single piece of text."""
        pass

    @abstractmethod
    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """Embed a list of texts."""
        pass
