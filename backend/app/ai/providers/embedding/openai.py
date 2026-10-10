from typing import List
from .base import BaseEmbeddingProvider

class OpenAIEmbeddingProvider(BaseEmbeddingProvider):
    provider_name = "openai"
    semantic = True

    def __init__(self, model_name: str = "text-embedding-3-small", api_key: str | None = None):
        from langchain_openai import OpenAIEmbeddings

        self.model_name = model_name
        self.embeddings = OpenAIEmbeddings(model=model_name, api_key=api_key)

    async def embed_text(self, text: str) -> List[float]:
        return await self.embeddings.aembed_query(text)

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        return await self.embeddings.aembed_documents(texts)
