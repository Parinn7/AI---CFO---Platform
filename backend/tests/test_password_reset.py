"""End-to-end tests for the password reset flow (task 2.4, FR-1.4).

Same in-memory SQLite + `get_db` override approach as the other endpoint tests.
Environment defaults to "development", so the request endpoint returns the
reset token inline (stub for the missing email service) — which lets these
tests drive the full request → confirm → login-with-new-password cycle.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
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
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


async def _signup(client: AsyncClient, email: str, password: str) -> None:
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": email, "password": password}
    )
    assert resp.status_code == 201


async def _request_reset(client: AsyncClient, email: str) -> dict:
    resp = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": email}
    )
    assert resp.status_code == 200
    return resp.json()


async def test_request_returns_token_in_dev_for_existing_user(client: AsyncClient):
    await _signup(client, "a@example.com", "old-password")
    body = await _request_reset(client, "a@example.com")
    assert body["reset_token"]
    assert "/reset-password?token=" in body["reset_link"]


async def test_request_unknown_email_is_generic_and_tokenless(client: AsyncClient):
    body = await _request_reset(client, "nobody@example.com")
    # Same message, but no token leaked -> no account enumeration.
    assert body["reset_token"] is None
    assert body["reset_link"] is None
    assert "if an account exists" in body["message"].lower()


async def test_full_reset_flow_lets_user_log_in_with_new_password(client: AsyncClient):
    await _signup(client, "a@example.com", "old-password")
    token = (await _request_reset(client, "a@example.com"))["reset_token"]

    confirm = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "brand-new-password"},
    )
    assert confirm.status_code == 200

    # Old password no longer works...
    old = await client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "old-password"},
    )
    assert old.status_code == 401
    # ...new one does.
    new = await client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.com", "password": "brand-new-password"},
    )
    assert new.status_code == 200


async def test_reset_token_is_single_use(client: AsyncClient):
    await _signup(client, "a@example.com", "old-password")
    token = (await _request_reset(client, "a@example.com"))["reset_token"]

    first = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "new-password-1"},
    )
    assert first.status_code == 200
    # Reusing the same token fails — the embedded fingerprint no longer matches.
    second = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "new-password-2"},
    )
    assert second.status_code == 400


async def test_confirm_rejects_garbage_token(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "not-a-real-token", "new_password": "whatever-123"},
    )
    assert resp.status_code == 400


async def test_confirm_rejects_short_password(client: AsyncClient):
    await _signup(client, "a@example.com", "old-password")
    token = (await _request_reset(client, "a@example.com"))["reset_token"]
    resp = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": token, "new_password": "short"},
    )
    assert resp.status_code == 422
