"""Abstract LLM provider interface.

All LLM providers (OpenAI, Claude, Gemini, Ollama, etc.) implement
this interface so consumers don't depend on any specific SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ChatMessage:
    """A single message in a chat conversation."""
    role: str  # "system", "user", "assistant"
    content: str


class LLMProvider(ABC):
    """Abstract base class for LLM providers.

    Subclasses must implement `chat()` and provide `name` and `model` properties.
    To add a new provider, create a subclass and register it in `LLMFactory`.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier (e.g. 'openai', 'claude', 'gemini')."""
        ...

    @property
    @abstractmethod
    def model(self) -> str:
        """Currently configured model name."""
        ...

    @abstractmethod
    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        json_mode: bool = False,
    ) -> str:
        """Send a chat completion request and return the response text.

        Args:
            messages: Conversation messages.
            temperature: Sampling temperature (0.0-2.0).
            max_tokens: Maximum tokens in the response.
            json_mode: If True, request structured JSON output.

        Returns:
            The assistant's response text.
        """
        ...
