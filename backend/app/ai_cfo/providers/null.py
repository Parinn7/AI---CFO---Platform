"""The disconnected provider (task 7.4, FR-6.4).

`LLM_PROVIDER=none`, and the fallback for a `gemini` that has no key yet.

This exists so that "no model is connected" is a *configuration*, not a special
case threaded through the service. `answer_question` has one path — assemble
the prompt, hand it to the provider, store what comes back — and the state the
project spends most of its life in (a fresh clone, CI, a marker branch, any
machine without a key) is just a provider that declines to answer. The service
catches `LLMNotConfigured` and stores the placeholder from 7.1: a reply that
quotes no figures and gives no advice, and says outright that the assistant
isn't wired up.

The alternative — a provider that returns canned prose — was rejected for the
same reason 7.1 rejected a plausible-sounding stub. A demo would show it and a
reader would believe it.
"""

from __future__ import annotations

from typing import ClassVar, Sequence

from app.ai_cfo.prompt import PromptMessage
from app.ai_cfo.providers.base import Completion, LLMNotConfigured, LLMProvider


class NullProvider(LLMProvider):
    """`LLM_PROVIDER=none` — answers nothing, honestly."""

    name: ClassVar[str] = "none"

    def __init__(self, model: str = "none") -> None:
        self.model = model

    @property
    def configured(self) -> bool:
        return False

    async def complete(self, messages: Sequence[PromptMessage]) -> Completion:
        raise LLMNotConfigured(
            "No LLM provider is configured (LLM_PROVIDER=none)."
        )


__all__ = ["NullProvider"]
