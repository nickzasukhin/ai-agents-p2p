"""LLM provider factory.

Central registry for creating LLM provider instances.
To add a new provider, import its class and add it to `_REGISTRY`.
"""

from __future__ import annotations

from src.llm.provider import LLMProvider


_REGISTRY: dict[str, type] = {}


def _ensure_registry():
    """Lazily populate the registry to avoid import-time side effects."""
    if _REGISTRY:
        return
    from src.llm.openai_provider import OpenAIProvider
    _REGISTRY["openai"] = OpenAIProvider


class LLMFactory:
    """Factory for creating LLM provider instances."""

    @staticmethod
    def create(provider: str, api_key: str, model: str | None = None) -> LLMProvider:
        """Create an LLM provider instance.

        Args:
            provider: Provider name (e.g. "openai").
            api_key: API key for the provider.
            model: Model name override. If None, uses provider default.

        Returns:
            An LLMProvider instance.

        Raises:
            ValueError: If the provider is not registered.
        """
        _ensure_registry()
        cls = _REGISTRY.get(provider)
        if cls is None:
            available = ", ".join(sorted(_REGISTRY.keys()))
            raise ValueError(
                f"Unknown LLM provider '{provider}'. Available: {available}"
            )

        kwargs: dict = {"api_key": api_key}
        if model:
            kwargs["model"] = model
        return cls(**kwargs)

    @staticmethod
    def available_providers() -> list[str]:
        """Return list of registered provider names."""
        _ensure_registry()
        return sorted(_REGISTRY.keys())
