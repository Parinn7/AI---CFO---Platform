"""End-to-end tests for the company profile endpoints (create/list/get/update).

Reuses the same in-memory SQLite + `get_db` override approach as test_auth.py.
Covers the owner-scoping guarantee (NFR-3): user A must never see or mutate
user B's company.
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app

# Register all model tables before create_all.
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


async def _register(client: AsyncClient, email: str) -> str:
    """Sign up a user and return an auth header token."""
    resp = await client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "sup3r-secret"},
    )
    assert resp.status_code == 201
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_create_company_defaults_currency_inr(client: AsyncClient):
    token = await _register(client, "a@example.com")
    resp = await client.post(
        "/api/v1/companies",
        headers=_auth(token),
        json={"name": "Acme SME", "industry": "Retail", "fiscal_year_start_month": 4},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Acme SME"
    assert body["industry"] == "Retail"
    assert body["fiscal_year_start_month"] == 4
    assert body["currency"] == "INR"
    assert body["id"]


async def test_create_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/companies", json={"name": "NoAuth Inc"})
    assert resp.status_code == 401


async def test_create_rejects_bad_fiscal_month(client: AsyncClient):
    token = await _register(client, "a@example.com")
    resp = await client.post(
        "/api/v1/companies",
        headers=_auth(token),
        json={"name": "Acme", "fiscal_year_start_month": 13},
    )
    assert resp.status_code == 422


async def test_list_returns_only_own_companies(client: AsyncClient):
    token_a = await _register(client, "a@example.com")
    token_b = await _register(client, "b@example.com")
    await client.post(
        "/api/v1/companies", headers=_auth(token_a), json={"name": "A Co"}
    )
    await client.post(
        "/api/v1/companies", headers=_auth(token_b), json={"name": "B Co"}
    )

    list_a = await client.get("/api/v1/companies", headers=_auth(token_a))
    assert list_a.status_code == 200
    names_a = [c["name"] for c in list_a.json()]
    assert names_a == ["A Co"]


async def test_cannot_read_another_users_company(client: AsyncClient):
    token_a = await _register(client, "a@example.com")
    token_b = await _register(client, "b@example.com")
    created = await client.post(
        "/api/v1/companies", headers=_auth(token_a), json={"name": "A Co"}
    )
    company_id = created.json()["id"]

    # B tries to read A's company -> 404 (not 403, to avoid leaking existence).
    resp = await client.get(f"/api/v1/companies/{company_id}", headers=_auth(token_b))
    assert resp.status_code == 404


async def test_update_company_partial(client: AsyncClient):
    token = await _register(client, "a@example.com")
    created = await client.post(
        "/api/v1/companies",
        headers=_auth(token),
        json={"name": "Old Name", "industry": "Retail", "fiscal_year_start_month": 1},
    )
    company_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/companies/{company_id}",
        headers=_auth(token),
        json={"name": "New Name", "fiscal_year_start_month": 7},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "New Name"
    assert body["fiscal_year_start_month"] == 7
    # Untouched field preserved.
    assert body["industry"] == "Retail"


async def test_cannot_update_another_users_company(client: AsyncClient):
    token_a = await _register(client, "a@example.com")
    token_b = await _register(client, "b@example.com")
    created = await client.post(
        "/api/v1/companies", headers=_auth(token_a), json={"name": "A Co"}
    )
    company_id = created.json()["id"]

    resp = await client.patch(
        f"/api/v1/companies/{company_id}",
        headers=_auth(token_b),
        json={"name": "Hijacked"},
    )
    assert resp.status_code == 404
