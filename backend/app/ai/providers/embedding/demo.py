import hashlib
from typing import List
from .base import BaseEmbeddingProvider

class DemoEmbeddingProvider(BaseEmbeddingProvider):
    """Deterministic, free, offline vectors derived from a text hash. They carry no meaning, so retrieval in Demo
    Mode ranks by keyword relevance instead of vector similarity (semantic = False)."""

    provider_name = "demo"
    model_name = "demo-hash-1536"
    semantic = False

    def __init__(self, dimension: int = 1536):
        self.dimension = dimension

    def _pseudo_random_vector(self, text: str) -> List[float]:
        """Generate a deterministic pseudo-random vector based on text hash."""
        vec = []
        hash_base = int(hashlib.md5(text.encode('utf-8')).hexdigest(), 16)
        
        # Simple deterministic distribution to spread values between -1 and 1
        for i in range(self.dimension):
            # Seed behavior with position i
            val = ((hash_base + i) % 2000) / 1000.0 - 1.0
            vec.append(val)
            
        # Normalize
        magnitude = sum(x*x for x in vec) ** 0.5
        if magnitude == 0:
            return [0.0] * self.dimension
        return [x / magnitude for x in vec]

    async def embed_text(self, text: str) -> List[float]:
        return self._pseudo_random_vector(text)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return [self._pseudo_random_vector(t) for t in texts]
