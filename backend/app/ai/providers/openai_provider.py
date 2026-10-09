from typing import Any, Type
from pydantic import BaseModel
from .base import BaseAIProvider
from ..prompts import PROVIDER_SYSTEM_PROMPT


class OpenAIProvider(BaseAIProvider):
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.7,
        api_key: str | None = None,
        timeout: float = 120.0,
    ):
        from langchain_openai import ChatOpenAI

        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=api_key,
            timeout=timeout,
        )

    @staticmethod
    def _messages(prompt: str):
        from langchain_core.messages import HumanMessage, SystemMessage

        return [SystemMessage(content=PROVIDER_SYSTEM_PROMPT), HumanMessage(content=prompt)]

    async def generate_structured(self, prompt: str, schema: Type[BaseModel]) -> Any:
        structured_llm = self.llm.with_structured_output(schema)
        result = await structured_llm.ainvoke(self._messages(prompt))
        return result

    async def generate_text(self, prompt: str) -> str:
        response = await self.llm.ainvoke(self._messages(prompt))
        return response.content
