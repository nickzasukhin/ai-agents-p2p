"""OpenAI LLM provider implementation."""

from __future__ import annotations

import structlog
from openai import OpenAI

from src.llm.provider import LLMProvider, ChatMessage

log = structlog.get_logger()


class OpenAIProvider(LLMProvider):
    """LLM provider backed by the OpenAI API.

    Wraps the synchronous `openai.OpenAI` client.
    """

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self._client = OpenAI(api_key=api_key)
        self._model = model

    @property
    def name(self) -> str:
        return "openai"

    @property
    def model(self) -> str:
        return self._model

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> str:
        kwargs: dict = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        log.debug("openai_chat_request", model=self._model, json_mode=json_mode)
        response = self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
