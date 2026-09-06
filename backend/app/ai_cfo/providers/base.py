"""The provider interface the AI CFO talks to (task 7.4, FR-6.4).

Everything above this module — the context (7.2), the system prompt (7.3), the
message assembly — is written against `PromptMessage`, a plain value with three
roles. This module is where that becomes a request to somebody's API, and it is
deliberately the *only* place in the codebase that knows which vendor is on the
other end.

**Why an interface rather than just calling Gemini.** FR-6.4 asks for the
provider to be swappable, and the reason is not hypothetical vendor-shopping:
an LLM API is the one dependency in this system that can be deprecated,
rate-limited or repriced without warning, and it sits behind the feature the
project is named after. The seam costs one small module per vendor and means a
swap is a config change plus a new file, rather than an edit to the prompt, the
service, the router and the tests.

**What the interface deliberately does not expose.** No streaming, no tool
calls, no function-calling, no structured output. The AI CFO asks one question
and gets back one block of prose; anything richer would be a place for a model
to start doing work that architecture §4.1 reserves for the Financial Engine.
Keeping the contract this narrow is what makes it genuinely portable — every
chat API in existence can satisfy "messages in, text out".

**Errors are a first-class part of the contract.** A provider never returns an
apology as its answer. If the call fails, it raises, and the failure carries a
sentence fit to show a user (`user_message`) separately from the detail worth
logging. That split matters here: the stored conversation is an audit trail, so
an outage must not end up persisted as something the assistant "said", and the
key that was rejected must not end up on someone's screen.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import ClassVar, Sequence

from app.ai_cfo.prompt import PromptMessage


class LLMError(Exception):
    """Base class for every way a provider call can fail.

    `user_message` is what a person may be shown; `str(exc)` is what goes in
    the log. They are different on purpose — provider errors routinely quote
    API keys, project ids and request payloads back at you.
    """

    #: Whether trying the same request again could plausibly work.
    retryable: ClassVar[bool] = False
    #: The sentence shown to the user when this is raised.
    user_message: ClassVar[str] = (
        "The AI CFO couldn't produce an answer just now. Please try again."
    )


class LLMNotConfigured(LLMError):
    """No provider is connected — no API key, or the provider is `none`.

    Not a failure: this is the state the project ships in, and the state a
    marker branch or a fresh clone starts in. The service answers with its
    placeholder rather than an error, and the chat screen says plainly that the
    model isn't wired up. See `ai_cfo.service.answer_question`.
    """

    user_message = (
        "The AI CFO isn't connected to a language model yet."
    )


class LLMConfigurationError(LLMError):
    """The provider *is* meant to be connected, but the configuration is wrong
    — an unknown `LLM_PROVIDER` name, most often a typo.

    Distinct from `LLMNotConfigured` because the two want opposite handling:
    an absent key is an expected state to degrade politely around, while a
    misspelled provider is a mistake that should be loud enough to notice
    rather than silently look like "not connected yet" forever.
    """

    user_message = (
        "The AI CFO is misconfigured on the server, so it can't answer. "
        "Check the LLM provider settings."
    )


class LLMAuthError(LLMError):
    """The provider rejected the credentials."""

    user_message = (
        "The AI CFO's connection to its language model was rejected. The API "
        "key looks wrong or expired."
    )


class LLMRequestError(LLMError):
    """The provider rejected the request itself — bad model name, malformed
    body, a prompt over the context limit."""

    user_message = (
        "The AI CFO couldn't ask its language model that question. This is a "
        "problem on our side, not with what you asked."
    )


class LLMUnavailable(LLMError):
    """The provider was unreachable, timed out, or returned a server error."""

    retryable = True
    user_message = (
        "The AI CFO couldn't reach its language model. It may be busy or "
        "briefly down — try again in a moment."
    )


class LLMRateLimited(LLMUnavailable):
    """Quota or rate limit exhausted."""

    user_message = (
        "The AI CFO has hit its usage limit with the language model. Try "
        "again shortly."
    )


class LLMRefused(LLMError):
    """The provider's safety filters blocked the prompt or the answer.

    Worth its own class rather than folding into `LLMRequestError`: a refusal
    is about *content*, so the honest thing to tell the user is that the
    question can be rephrased, not that something broke.
    """

    user_message = (
        "The language model declined to answer that one. Try rephrasing the "
        "question."
    )


class LLMEmptyResponse(LLMError):
    """The call succeeded and came back with no usable text.

    Rare, but it happens — a response truncated before any prose was emitted,
    or a candidate with no text parts. It is a failure rather than an empty
    answer because storing a blank assistant turn would leave a conversation
    that reads as though the assistant ignored the question.

    Not retryable: the causes that actually produce it — an output budget spent
    on reasoning tokens, a response filtered down to nothing — are properties of
    the request, so a second attempt returns the same nothing.
    """

    user_message = (
        "The AI CFO's language model came back empty. Please try again."
    )


@dataclass(frozen=True)
class TokenUsage:
    """What one call cost, in tokens. Logged, never shown to the user."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass(frozen=True)
class Completion:
    """One answer, plus what produced it.

    `provider` and `model` travel with the text because the chat is an audit
    trail: `kpi_context_snapshot_id` already records *what figures* an answer
    was built from, and this records *what wrote it*. Today both are logged
    rather than stored — the tables have no column for them (schema §9) and
    inventing one is not this task — but the value is carried here so that
    recording it later is a migration, not a rewrite.
    """

    text: str
    provider: str
    model: str
    finish_reason: str | None = None
    usage: TokenUsage | None = None


class LLMProvider(abc.ABC):
    """Messages in, text out. The whole contract.

    Implementations are constructed by `providers.get_provider` from settings
    and are expected to be cheap to build and safe to reuse across requests
    (they hold configuration, not connections — see `gemini.GeminiProvider`,
    which opens and closes its HTTP client per call).
    """

    #: The value of `LLM_PROVIDER` that selects this implementation.
    name: ClassVar[str]

    #: The model this instance will call, for logging and for the status the
    #: chat screen shows. A provider with nothing configured still has one.
    model: str

    @property
    def configured(self) -> bool:
        """Whether a call would actually reach a model.

        Read by `GET /chat/provider` so the UI can state the truth about
        itself, and by the service to decide between a real call and the
        placeholder. Never raises — asking whether something is connected must
        work in exactly the case where it isn't.
        """
        return True

    @abc.abstractmethod
    async def complete(self, messages: Sequence[PromptMessage]) -> Completion:
        """Send an assembled prompt and return the answer.

        `messages` is what `prompt.build_messages` produced: exactly one
        `system` message first, then alternating history, then the question.
        Implementations map those three roles onto whatever their API calls
        them and must not otherwise rewrite the content — the prompt is the
        product of 7.2 and 7.3, and a provider quietly appending to it would
        put text in front of the model that no one can read on `/chat`.

        Raises `LLMError` (never returns an error string) on any failure.
        """


__all__ = [
    "Completion",
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
    "TokenUsage",
]
