"""The LLM provider behind the AI CFO (task 7.4, FR-6.4).

Two halves, and the split matters.

The **provider** tests pin the one place in the codebase that speaks a vendor's
dialect: that the system prompt lands in Gemini's `system_instruction` rather
than in the turn history, that the assistant's role is renamed `model`, that a
200 carrying no usable answer is treated as a failure rather than stored as an
empty reply, and that each HTTP status maps to an error the caller can act on.
They run against `httpx.MockTransport` — no key, no network, and the request
body is asserted rather than hoped about.

The **service and endpoint** tests pin what the rest of the app does with a
provider: a connected one's words are stored verbatim and grounded in a
snapshot, an unconfigured one still yields the inert placeholder, and a failing
one leaves nothing behind at all. Those go through the real API with a
substituted provider, because "nothing is written when the call fails" is a
claim about a database transaction, not about a function's return value.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncGenerator, Sequence

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai_cfo.models import ChatMessage
from app.ai_cfo.prompt import ASSISTANT, SYSTEM, USER, PromptMessage
from app.ai_cfo.providers import (
    Completion,
    GeminiProvider,
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
    NullProvider,
    available_providers,
    get_provider,
)
from app.ai_cfo.providers import gemini as gemini_module
from app.ai_cfo.router import current_provider
from app.ai_cfo.service import PLACEHOLDER_REPLY
from app.core.config import Settings
from app.core.database import Base, get_db
from app.main import app

from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401
from app.financial_engine import models as _fin_models  # noqa: F401
from app.scenarios import models as _scenario_models  # noqa: F401
from app.ai_cfo import models as _ai_cfo_models  # noqa: F401

pytestmark = pytest.mark.asyncio


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _messages() -> tuple[PromptMessage, ...]:
    """A prompt shaped exactly like `build_messages` produces one."""
    return (
        PromptMessage(role=SYSTEM, content="RULES\n\nFIGURES\n- Burn rate: ₹4,21,573.50"),
        PromptMessage(role=USER, content="How long will my cash last?"),
        PromptMessage(role=ASSISTANT, content="About 17.29 months."),
        PromptMessage(role=USER, content="And if I hire two engineers?"),
    )


def _answer(text: str = "Your runway is 17.29 months.") -> dict:
    return {
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": text}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": 1200,
            "candidatesTokenCount": 80,
            "totalTokenCount": 1280,
        },
    }


def _provider(handler, **kwargs) -> GeminiProvider:
    """A Gemini provider wired to a mock transport instead of the internet."""
    return GeminiProvider(
        api_key="test-key",
        model="gemini-3.8-flash",
        transport=httpx.MockTransport(handler),
        **kwargs,
    )


class FakeProvider(LLMProvider):
    """A provider that answers, fails, or reports itself unconfigured on cue,
    and remembers what it was asked."""

    name = "fake"

    def __init__(
        self,
        *,
        reply: str = "Your cash lasts about 17.29 months.",
        error: LLMError | None = None,
        configured: bool = True,
    ) -> None:
        self.model = "fake-1"
        self._reply = reply
        self._error = error
        self._configured = configured
        self.seen: list[PromptMessage] = []

    @property
    def configured(self) -> bool:
        return self._configured

    async def complete(self, messages: Sequence[PromptMessage]) -> Completion:
        self.seen = list(messages)
        if self._error is not None:
            raise self._error
        return Completion(text=self._reply, provider=self.name, model=self.model)


# --------------------------------------------------------------------------
# The registry
# --------------------------------------------------------------------------


async def test_registry_builds_the_configured_provider():
    gemini = get_provider(Settings(llm_provider="gemini", llm_api_key="k"))
    assert isinstance(gemini, GeminiProvider)
    assert gemini.configured

    none = get_provider(Settings(llm_provider="none"))
    assert isinstance(none, NullProvider)
    assert not none.configured


async def test_provider_name_is_read_leniently():
    """A stray capital or space in a `.env` shouldn't look like a typo."""
    assert isinstance(
        get_provider(Settings(llm_provider="  Gemini ", llm_api_key="k")),
        GeminiProvider,
    )


async def test_unknown_provider_is_an_error_not_a_silent_fallback():
    """A misspelled provider must not degrade into 'not connected yet' — the
    two states look identical on screen and want opposite fixes."""
    with pytest.raises(LLMConfigurationError) as exc:
        get_provider(Settings(llm_provider="openai"))
    assert "gemini" in str(exc.value)
    assert set(available_providers()) == {"gemini", "none"}


async def test_a_gemini_without_a_key_is_not_configured_but_is_not_an_error():
    """The state this project shipped 7.1–7.3 in, and the state a fresh clone
    starts in: a real provider, no key, no exception until something asks it to
    answer."""
    provider = get_provider(Settings(llm_provider="gemini", llm_api_key=""))
    assert not provider.configured
    assert provider.model  # still names the model it would call
    with pytest.raises(LLMNotConfigured):
        await provider.complete(_messages())


# --------------------------------------------------------------------------
# The Gemini request
# --------------------------------------------------------------------------


async def test_the_system_prompt_travels_as_system_instruction():
    """Not as a turn in the conversation. The FIGURES block is standing
    instruction (7.2/7.3), and a model that reads it as something 'said'
    earlier can treat it as superseded by later turns."""
    payload = _provider(lambda r: httpx.Response(200)).build_payload(_messages())

    assert "Burn rate" in payload["system_instruction"]["parts"][0]["text"]
    assert [c["role"] for c in payload["contents"]] == ["user", "model", "user"]
    # The rules and figures appear once, and not inside the turn history.
    assert all(
        "FIGURES" not in part["text"]
        for content in payload["contents"]
        for part in content["parts"]
    )


async def test_the_assistant_role_is_renamed_for_gemini():
    payload = _provider(lambda r: httpx.Response(200)).build_payload(_messages())
    assert payload["contents"][1] == {
        "role": "model",
        "parts": [{"text": "About 17.29 months."}],
    }


async def test_generation_config_is_sized_for_prose_not_reasoning():
    """Thinking tokens come out of the same budget as the answer; this
    assistant is forbidden from reasoning over numbers anyway (§4.1)."""
    payload = _provider(
        lambda r: httpx.Response(200), max_output_tokens=1024, temperature=0.2
    ).build_payload(_messages())
    config = payload["generationConfig"]
    assert config["maxOutputTokens"] == 1024
    assert config["temperature"] == 0.2
    assert config["thinkingConfig"]["thinkingBudget"] == 0


async def test_the_api_key_goes_in_a_header_never_the_url():
    """A URL with a key in it ends up in access logs and stack traces."""
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-goog-api-key")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_answer())

    await _provider(handler).complete(_messages())

    assert seen["key"] == "test-key"
    assert "test-key" not in seen["url"]
    assert seen["url"].endswith("/models/gemini-3.8-flash:generateContent")
    assert "contents" in seen["body"]


# --------------------------------------------------------------------------
# The Gemini response
# --------------------------------------------------------------------------


async def test_a_successful_call_returns_the_text_and_what_produced_it():
    completion = await _provider(
        lambda r: httpx.Response(200, json=_answer())
    ).complete(_messages())

    assert completion.text == "Your runway is 17.29 months."
    assert (completion.provider, completion.model) == ("gemini", "gemini-3.8-flash")
    assert completion.finish_reason == "STOP"
    assert completion.usage.prompt_tokens == 1200
    assert completion.usage.completion_tokens == 80


async def test_multipart_answers_are_joined():
    body = {
        "candidates": [
            {
                "content": {"parts": [{"text": "Your runway "}, {"text": "is fine."}]},
                "finishReason": "STOP",
            }
        ]
    }
    completion = await _provider(lambda r: httpx.Response(200, json=body)).complete(
        _messages()
    )
    assert completion.text == "Your runway is fine."


async def test_a_blocked_prompt_is_a_refusal_not_a_crash():
    body = {"promptFeedback": {"blockReason": "SAFETY"}}
    with pytest.raises(LLMRefused):
        await _provider(lambda r: httpx.Response(200, json=body)).complete(_messages())


async def test_an_answer_truncated_before_any_prose_is_a_failure():
    """A 200 is not the same as an answer. Storing the empty string would leave
    a conversation that reads as though the assistant ignored the question."""
    body = {"candidates": [{"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]}
    with pytest.raises(LLMEmptyResponse) as exc:
        await _provider(lambda r: httpx.Response(200, json=body)).complete(_messages())
    assert "LLM_MAX_OUTPUT_TOKENS" in str(exc.value)


async def test_no_candidates_is_a_failure():
    with pytest.raises(LLMEmptyResponse):
        await _provider(lambda r: httpx.Response(200, json={"candidates": []})).complete(
            _messages()
        )


# --------------------------------------------------------------------------
# Failure mapping and retries
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (401, LLMAuthError),
        (403, LLMAuthError),
        (400, LLMRequestError),
        (404, LLMRequestError),
        (429, LLMRateLimited),
        (500, LLMUnavailable),
        (503, LLMUnavailable),
    ],
)
async def test_http_statuses_map_to_actionable_errors(status_code, expected, monkeypatch):
    monkeypatch.setattr(gemini_module, "RETRY_DELAY_SECONDS", 0)
    body = {"error": {"message": "something went wrong", "status": "X"}}
    with pytest.raises(expected):
        await _provider(
            lambda r: httpx.Response(status_code, json=body)
        ).complete(_messages())


async def test_a_timeout_is_reported_as_unavailable(monkeypatch):
    monkeypatch.setattr(gemini_module, "RETRY_DELAY_SECONDS", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("too slow", request=request)

    with pytest.raises(LLMUnavailable):
        await _provider(handler).complete(_messages())


async def test_a_transient_failure_is_retried_once_then_succeeds(monkeypatch):
    monkeypatch.setattr(gemini_module, "RETRY_DELAY_SECONDS", 0)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, json={"error": {"message": "overloaded"}})
        return httpx.Response(200, json=_answer())

    completion = await _provider(handler).complete(_messages())
    assert calls["n"] == 2
    assert completion.text == "Your runway is 17.29 months."


async def test_a_rejected_key_is_not_retried(monkeypatch):
    """It will be rejected identically the second time; retrying only doubles
    the wait before the user is told."""
    monkeypatch.setattr(gemini_module, "RETRY_DELAY_SECONDS", 0)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    with pytest.raises(LLMAuthError):
        await _provider(handler).complete(_messages())
    assert calls["n"] == 1


async def test_error_detail_is_logged_not_shown():
    """`user_message` is what a person may read; `str(exc)` is for the log.
    Provider errors quote keys and payloads back at you."""
    body = {"error": {"message": "API key AIzaSyLEAKED is invalid"}}
    with pytest.raises(LLMAuthError) as exc:
        await _provider(lambda r: httpx.Response(401, json=body)).complete(_messages())
    assert "AIzaSyLEAKED" in str(exc.value)
    assert "AIzaSyLEAKED" not in exc.value.user_message


# --------------------------------------------------------------------------
# The service and the endpoint
# --------------------------------------------------------------------------


@pytest_asyncio.fixture
async def env() -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac, session_factory
    app.dependency_overrides.clear()
    await engine.dispose()


async def _signup(client: AsyncClient, email: str) -> dict:
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "sup3r-secret"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _company(client: AsyncClient, headers: dict) -> str:
    return (
        await client.post(
            "/api/v1/companies", headers=headers, json={"name": "Northwind Analytics"}
        )
    ).json()["id"]


async def _session(client: AsyncClient, headers: dict, cid: str) -> str:
    return (
        await client.post(
            "/api/v1/chat/sessions", headers=headers, json={"company_id": cid}
        )
    ).json()["id"]


async def test_a_connected_provider_answer_is_stored_verbatim(env):
    client, session_factory = env
    provider = FakeProvider(reply="You have about 17.29 months of runway.")
    app.dependency_overrides[current_provider] = lambda: provider

    headers = await _signup(client, "connected@example.com")
    sid = await _session(client, headers, await _company(client, headers))
    turn = (
        await client.post(
            f"/api/v1/chat/sessions/{sid}/messages",
            headers=headers,
            json={"content": "How long will my cash last?"},
        )
    ).json()

    assert turn["assistant_message"]["content"] == "You have about 17.29 months of runway."
    # It is the model's words that were stored, not an echo of the request.
    detail = (await client.get(f"/api/v1/chat/sessions/{sid}", headers=headers)).json()
    assert detail["messages"][1]["content"] == "You have about 17.29 months of runway."
    # And the prompt it was given is the one 7.3 assembles: system first.
    assert provider.seen[0].role == SYSTEM
    assert provider.seen[-1].content == "How long will my cash last?"


async def test_an_unconfigured_provider_still_answers_with_the_placeholder(env):
    """The default state of this project. A working screen, not an error."""
    client, _ = env
    app.dependency_overrides[current_provider] = lambda: NullProvider()

    headers = await _signup(client, "unconfigured@example.com")
    sid = await _session(client, headers, await _company(client, headers))
    resp = await client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        headers=headers,
        json={"content": "What is my burn rate?"},
    )

    assert resp.status_code == 201
    assert resp.json()["assistant_message"]["content"] == PLACEHOLDER_REPLY


async def test_a_failed_call_answers_503_and_stores_nothing(env):
    """`chat_messages` is an audit trail. An outage must not be recorded as
    something the assistant said, and a question with no answer must not be
    left sitting in the history."""
    client, session_factory = env
    app.dependency_overrides[current_provider] = lambda: FakeProvider(
        error=LLMUnavailable("gemini is down")
    )

    headers = await _signup(client, "outage@example.com")
    sid = await _session(client, headers, await _company(client, headers))
    resp = await client.post(
        f"/api/v1/chat/sessions/{sid}/messages",
        headers=headers,
        json={"content": "How long will my cash last?"},
    )

    assert resp.status_code == 503
    assert "try again" in resp.json()["detail"].lower()
    assert "gemini is down" not in resp.json()["detail"]

    async with session_factory() as db:
        stored = (
            await db.execute(
                select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(sid))
            )
        ).scalars().all()
    assert stored == []

    detail = (await client.get(f"/api/v1/chat/sessions/{sid}", headers=headers)).json()
    assert detail["messages"] == []


async def test_the_provider_endpoint_reports_status_without_leaking_the_key(env):
    client, _ = env
    app.dependency_overrides[current_provider] = lambda: GeminiProvider(
        api_key="super-secret", model="gemini-3.8-flash"
    )

    headers = await _signup(client, "status@example.com")
    body = (await client.get("/api/v1/chat/provider", headers=headers)).json()

    assert body == {
        "provider": "gemini",
        "model": "gemini-3.8-flash",
        "configured": True,
    }
    assert "super-secret" not in json.dumps(body)


async def test_the_provider_endpoint_requires_a_login(env):
    """It describes server configuration; anonymous callers don't get to
    enumerate it."""
    client, _ = env
    assert (await client.get("/api/v1/chat/provider")).status_code == 401
