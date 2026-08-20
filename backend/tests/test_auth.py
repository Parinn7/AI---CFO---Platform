"""End-to-end tests for the auth endpoints (signup / login / me).

Runs against an in-memory SQLite database (StaticPool so every session shares
one connection) with `get_db` overridden — no live Postgres required. Exercises
the real routers, schemas, service, hashing, and JWT dependency together.
"""

from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

# Import models so their tables are registered on Base.metadata before create_all.
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

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
    await engine.dispose()


SIGNUP = {"email": "founder@example.com", "password": "sup3r-secret", "full_name": "Ada"}


async def test_signup_returns_token_and_user(client: AsyncClient):
    resp = await client.post("/api/v1/auth/signup", json=SIGNUP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "founder@example.com"
    assert body["user"]["full_name"] == "Ada"
    assert "password" not in body["user"]
    assert "password_hash" not in body["user"]


async def test_signup_duplicate_email_conflicts(client: AsyncClient):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    # Same email, different case — should still collide (emails normalised).
    dup = {**SIGNUP, "email": "Founder@Example.com"}
    resp = await client.post("/api/v1/auth/signup", json=dup)
    assert resp.status_code == 409


async def test_signup_rejects_short_password(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/signup", json={"email": "x@example.com", "password": "short"}
    )
    assert resp.status_code == 422


async def test_login_succeeds_with_correct_credentials(client: AsyncClient):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "sup3r-secret"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_wrong_password_is_401(client: AsyncClient):
    await client.post("/api/v1/auth/signup", json=SIGNUP)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "founder@example.com", "password": "nope"},
    )
    assert resp.status_code == 401


async def test_login_unknown_email_is_401(client: AsyncClient):
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "ghost@example.com", "password": "whatever"},
    )
    assert resp.status_code == 401


async def test_me_returns_current_user_with_token(client: AsyncClient):
    token = (await client.post("/api/v1/auth/signup", json=SIGNUP)).json()[
        "access_token"
    ]
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "founder@example.com"


@pytest.mark.parametrize("headers", [{}, {"Authorization": "Bearer garbage"}])
async def test_me_requires_valid_token(client: AsyncClient, headers: dict):
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401
