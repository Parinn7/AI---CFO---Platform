"""Google Gemini, behind the provider interface (task 7.4, FR-6.4).

The provider the project actually runs on. Chosen for its free development
tier, which matters for a capstone that has to be demonstrable without a
billing account attached to it.

**Called over plain REST with `httpx`, not the vendor SDK.** The interface in
`base.py` needs one thing from a provider — messages in, text out — and the
`generateContent` endpoint gives exactly that in about eighty lines. Pulling in
an SDK to reach it would add a dependency that ships its own auth, transport,
retry and telemetry stack (and its own Python-version support matrix, which is
a live concern on 3.14) in exchange for a JSON body this module can write out
in full, where every field is visible and testable. `httpx` was already a
dependency here for the test client.

**The mapping.** Gemini keeps the system prompt out of the turn history in its
own `system_instruction` field, and names the assistant's role `model`. That is
a good fit for this prompt: the FIGURES block is standing instruction rather
than something "said" earlier in the conversation, so it stays structurally
separate from anything the user or the model has said, and can't be mistaken
for a turn.

**Thinking is off by default.** Gemini 2.5 models reason before answering and
those tokens are billed against the same output budget as the answer, which on
a small `maxOutputTokens` can consume the entire allowance and return a
truncated candidate with no text at all. The AI CFO's job is to explain figures
it has been handed in plain language, not to work anything out — architecture
§4.1 makes reasoning over numbers the one thing it must not do — so the budget
is zero and the whole allowance goes to prose. `LLM_THINKING_BUDGET` can raise
it (`-1` for dynamic); note that not every model accepts `0` — the 2.5 pro
models require at least 128.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Sequence

import httpx

from app.ai_cfo.prompt import ASSISTANT, SYSTEM, USER, PromptMessage
from app.ai_cfo.providers.base import (
    Completion,
    LLMAuthError,
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

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# Pinned rather than tracking the `gemini-flash-latest` alias. This has to work
# on the day of a presentation, and a model that silently changes underneath a
# fixed system prompt is a worse risk than one that eventually needs bumping —
# Google retires older ids for new keys (2.5-flash already returns a 404 with
# an upgrade hint), which is a loud, readable failure rather than a quiet
# change in behaviour.
DEFAULT_MODEL = "gemini-3.8-flash"

# One retry, on failures that are plausibly a blip: a timeout, a dropped
# connection, a 429 or a 5xx. Not a backoff ladder — someone is watching a
# "Thinking…" indicator, and a request that has already failed twice is better
# reported than waited on.
MAX_ATTEMPTS = 2
RETRY_DELAY_SECONDS = 1.0

# Finish reasons that mean the model was stopped on content grounds rather than
# having said its piece.
_BLOCKED_FINISH_REASONS = frozenset(
    {"SAFETY", "BLOCKLIST", "PROHIBITED_CONTENT", "SPII", "IMAGE_SAFETY", "RECITATION"}
)


class GeminiProvider(LLMProvider):
    """`LLM_PROVIDER=gemini`."""

    name: ClassVar[str] = "gemini"

    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        *,
        timeout_seconds: float = 30.0,
        max_output_tokens: int = 1024,
        temperature: float = 0.2,
        thinking_budget: int = 0,
        base_url: str = DEFAULT_BASE_URL,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key.strip()
        self.model = model.strip() or DEFAULT_MODEL
        self._timeout = timeout_seconds
        self._max_output_tokens = max_output_tokens
        self._temperature = temperature
        self._thinking_budget = thinking_budget
        self._base_url = base_url.rstrip("/")
        # Test seam: a `MockTransport` lets the request body and the response
        # handling be pinned without a network or a key. Nothing in the app
        # passes it.
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    # --- request building -------------------------------------------------

    def build_payload(self, messages: Sequence[PromptMessage]) -> dict[str, Any]:
        """The `generateContent` body for an assembled prompt.

        Public because it is worth testing directly: this is the exact point
        where 7.2's figures and 7.3's rules turn into somebody else's schema,
        and a silent mis-mapping here (the system prompt landing in the turn
        history, the roles inverted) would be invisible in an answer that still
        reads plausibly.
        """
        system_parts: list[str] = []
        contents: list[dict[str, Any]] = []

        for message in messages:
            if message.role == SYSTEM:
                system_parts.append(message.content)
                continue
            # Gemini calls the assistant "model"; user is user.
            role = "model" if message.role == ASSISTANT else "user"
            contents.append({"role": role, "parts": [{"text": message.content}]})

        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {
                # Low but not zero. These answers explain figures rather than
                # generate them, so variation buys nothing; a little is kept so
                # asking the same question twice doesn't read like a lookup.
                "temperature": self._temperature,
                "maxOutputTokens": self._max_output_tokens,
                "thinkingConfig": {"thinkingBudget": self._thinking_budget},
            },
        }
        if system_parts:
            payload["system_instruction"] = {
                "parts": [{"text": "\n\n".join(system_parts)}]
            }
        return payload

    # --- the call ---------------------------------------------------------

    async def complete(self, messages: Sequence[PromptMessage]) -> Completion:
        if not self.configured:
            raise LLMNotConfigured("LLM_API_KEY is empty; no Gemini key configured.")

        url = f"{self._base_url}/models/{self.model}:generateContent"
        payload = self.build_payload(messages)

        last_error: LLMError | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                data = await self._post(url, payload)
                return self._to_completion(data)
            except LLMError as exc:
                # `retryable` is the error's own judgement (see base.py): a
                # rejected key or a blocked prompt will fail identically the
                # second time, and retrying it only doubles the wait before the
                # user is told.
                if not exc.retryable:
                    raise
                last_error = exc
                logger.warning(
                    "Gemini call failed (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc
                )
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(RETRY_DELAY_SECONDS)

        assert last_error is not None  # the loop only exits by return or here
        raise last_error

    async def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        """One HTTP round trip, with transport and status errors translated.

        The client is opened per call rather than held for the life of the
        process. A pooled client is faster, but it has to be closed on shutdown
        and it makes the provider stateful — and this is one request per
        question typed by one person, where a connection setup is lost in the
        noise of the model's own latency.

        The key goes in a header, never the query string: a URL with an API key
        in it ends up in access logs and in exception messages.
        """
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout, transport=self._transport
            ) as client:
                response = await client.post(
                    url,
                    headers={
                        "x-goog-api-key": self._api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            raise LLMUnavailable(f"Gemini request timed out: {exc!r}") from exc
        except httpx.HTTPError as exc:
            raise LLMUnavailable(f"Gemini request failed: {exc!r}") from exc

        if response.status_code >= 400:
            raise self._status_error(response)

        try:
            return response.json()
        except ValueError as exc:
            raise LLMUnavailable("Gemini returned a non-JSON body.") from exc

    @staticmethod
    def _status_error(response: httpx.Response) -> Exception:
        """Map an HTTP status onto the interface's error classes."""
        detail = GeminiProvider._error_detail(response)
        status = response.status_code

        if status in (401, 403):
            return LLMAuthError(f"Gemini rejected the API key ({status}): {detail}")
        if status == 429:
            return LLMRateLimited(f"Gemini quota exhausted (429): {detail}")
        if status == 404:
            # The path tail is "<model>:generateContent"; the method name in
            # the message would just be noise.
            model = response.url.path.rsplit("/", 1)[-1].split(":", 1)[0]
            return LLMRequestError(
                f"Gemini has no model named {model!r} (404): {detail}"
            )
        if status >= 500:
            return LLMUnavailable(f"Gemini server error ({status}): {detail}")
        return LLMRequestError(f"Gemini rejected the request ({status}): {detail}")

    @staticmethod
    def _error_detail(response: httpx.Response) -> str:
        """The `error.message` from a Gemini error body, or the raw text.

        Truncated: these can carry the echoed request, and the whole point of
        the message/`user_message` split is that this half goes to a log.
        """
        try:
            body = response.json()
        except ValueError:
            return response.text[:500]
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("message", error))[:500]
        return str(body)[:500]

    # --- response parsing -------------------------------------------------

    def _to_completion(self, data: dict[str, Any]) -> Completion:
        """Pull the answer out of a `generateContent` response.

        A 200 is not the same as an answer. The response can carry a blocked
        prompt, a candidate stopped on safety grounds, or a candidate truncated
        before it emitted any prose. Each of those is raised rather than
        returned — see `LLMEmptyResponse` on why a blank turn must never be
        stored.
        """
        feedback = data.get("promptFeedback") or {}
        block_reason = feedback.get("blockReason")
        if block_reason:
            raise LLMRefused(f"Gemini blocked the prompt: {block_reason}")

        candidates = data.get("candidates") or []
        if not candidates:
            raise LLMEmptyResponse("Gemini returned no candidates.")

        candidate = candidates[0]
        finish_reason = candidate.get("finishReason")
        parts = (candidate.get("content") or {}).get("parts") or []
        text = "".join(
            part["text"] for part in parts if isinstance(part.get("text"), str)
        ).strip()

        if not text:
            if finish_reason in _BLOCKED_FINISH_REASONS:
                raise LLMRefused(f"Gemini stopped on content grounds: {finish_reason}")
            if finish_reason == "MAX_TOKENS":
                raise LLMEmptyResponse(
                    "Gemini hit maxOutputTokens before writing an answer — raise "
                    "LLM_MAX_OUTPUT_TOKENS or lower LLM_THINKING_BUDGET."
                )
            raise LLMEmptyResponse(
                f"Gemini returned an empty answer (finishReason={finish_reason})."
            )

        usage_data = data.get("usageMetadata") or {}
        usage = TokenUsage(
            prompt_tokens=usage_data.get("promptTokenCount"),
            completion_tokens=usage_data.get("candidatesTokenCount"),
            total_tokens=usage_data.get("totalTokenCount"),
        )
        return Completion(
            text=text,
            provider=self.name,
            model=self.model,
            finish_reason=finish_reason,
            usage=usage,
        )


__all__ = ["DEFAULT_BASE_URL", "DEFAULT_MODEL", "GeminiProvider"]
