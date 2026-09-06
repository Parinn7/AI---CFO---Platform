"""Provider registry for the AI CFO (task 7.4, FR-6.4).

One place that turns `LLM_PROVIDER` into an object satisfying
`base.LLMProvider`. Adding a vendor is a module plus a line in `_REGISTRY`;
nothing else in the codebase learns its name.

**Built per call, not cached.** A provider holds configuration — a key, a model
name, a timeout — and opens its HTTP connection inside `complete`, so
constructing one is a few attribute assignments. Caching it would buy nothing
and would mean an edited `.env` needed a process restart to take effect, which
is exactly the wrong tradeoff while someone is getting a key working.
"""

from __future__ import annotations

from typing import Callable

from app.ai_cfo.providers.base import (
    Completion,
    LLMAuthError,
    LLMConfigurationError,
    LLMEmptyResponse,
    LLMError,
    LLMNotConfigured,
    LLMProvider,
    LLMRateLimited,
    LLMRefused,
    LLMRequestError,
    LLMUnavailable,
    TokenUsage,
)
from app.ai_cfo.providers.gemini import DEFAULT_MODEL, GeminiProvider
from app.ai_cfo.providers.null import NullProvider
from app.core.config import Settings, settings as app_settings


def _build_gemini(settings: Settings) -> LLMProvider:
    return GeminiProvider(
        api_key=settings.llm_api_key,
        model=settings.llm_model or DEFAULT_MODEL,
        timeout_seconds=settings.llm_timeout_seconds,
        max_output_tokens=settings.llm_max_output_tokens,
        temperature=settings.llm_temperature,
        thinking_budget=settings.llm_thinking_budget,
    )


def _build_null(settings: Settings) -> LLMProvider:
    return NullProvider()


_REGISTRY: dict[str, Callable[[Settings], LLMProvider]] = {
    GeminiProvider.name: _build_gemini,
    NullProvider.name: _build_null,
}


def available_providers() -> tuple[str, ...]:
    """Every accepted value of `LLM_PROVIDER`."""
    return tuple(sorted(_REGISTRY))


def get_provider(settings: Settings | None = None) -> LLMProvider:
    """The configured provider.

    An unrecognised name raises `LLMConfigurationError` rather than quietly
    falling back to `none`. The two states look identical from the chat screen
    — no answers — but one is the expected "no key yet" and the other is a typo
    that would otherwise sit undiagnosed for as long as nobody reads the
    settings file. Empty *keys* are not this error: those are handled by the
    provider reporting `configured = False`, which is the normal way to run
    this project before a key exists.
    """
    settings = settings or app_settings
    name = (settings.llm_provider or "").strip().lower()
    factory = _REGISTRY.get(name)
    if factory is None:
        raise LLMConfigurationError(
            f"Unknown LLM_PROVIDER {settings.llm_provider!r}. "
            f"Expected one of: {', '.join(available_providers())}."
        )
    return factory(settings)


__all__ = [
    "Completion",
    "GeminiProvider",
    "LLMAuthError",
    "LLMConfigurationError",
    "LLMEmptyResponse",
    "LLMError",
    "LLMNotConfigured",
    "LLMProvider",
    "LLMRateLimited",
    "LLMRefused",
    "LLMRequestError",
    "LLMUnavailable",
    "NullProvider",
    "TokenUsage",
    "available_providers",
    "get_provider",
]
