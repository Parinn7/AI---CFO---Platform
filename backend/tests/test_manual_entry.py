"""End-to-end tests for the categories list + guided manual entry (task 3.3).

Same in-memory SQLite + get_db override as the other endpoint tests; the fixture
seeds the default categories (create_all doesn't run migration 0002).
"""

from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.transactions.categories import DEFAULT_CATEGORIES
from app.transactions.models import Category

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
    async with session_factory() as session:
        session.add_all(
            [Category(company_id=None, name=n, type=t) for n, t in DEFAULT_CATEGORIES]
        )
        await session.commit()

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


async def _auth(client: AsyncClient, email: str = "a@example.com") -> dict:
    token = (
        await client.post(
            "/api/v1/auth/signup", json={"email": email, "password": "sup3r-secret"}
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _company(client: AsyncClient, headers: dict) -> str:
    return (
        await client.post("/api/v1/companies", headers=headers, json={"name": "Acme"})
    ).json()["id"]


async def _categories(client: AsyncClient, headers: dict, cid: str) -> dict[str, dict]:
    resp = await client.get(
        "/api/v1/categories", headers=headers, params={"company_id": cid}
    )
    assert resp.status_code == 200
    return {c["name"]: c for c in resp.json()}


async def test_list_categories_returns_defaults(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    assert set(cats) == {
        "Revenue", "Payroll", "Rent", "Marketing", "Software/Tools",
        "Operations", "Other",
    }
    assert cats["Revenue"]["type"] == "income"
    assert cats["Rent"]["type"] == "expense"


async def test_list_categories_requires_auth(client: AsyncClient):
    resp = await client.get(
        "/api/v1/categories",
        params={"company_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 401


async def test_manual_entry_uses_category_type_and_is_manual(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)

    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {"date": "2026-01-31", "amount": "150000", "category_id": cats["Revenue"]["id"]},
                {"date": "2026-01-31", "amount": "40000", "category_id": cats["Payroll"]["id"]},
            ],
        },
    )
    assert resp.status_code == 201
    created = resp.json()
    assert len(created) == 2
    by_type = {t["type"]: t for t in created}
    assert by_type["income"]["source"] == "manual"
    assert by_type["income"]["upload_batch_id"] is None
    assert float(by_type["income"]["amount"]) == 150000.0
    assert by_type["expense"]["category_id"] == cats["Payroll"]["id"]


async def test_manual_entry_explicit_type_override(client: AsyncClient):
    """'Other' is an expense category, but the flow can flag an entry as income."""
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {
                    "date": "2026-02-10",
                    "amount": "5000",
                    "category_id": cats["Other"]["id"],
                    "type": "income",
                    "description": "Interest income",
                }
            ],
        },
    )
    assert resp.status_code == 201
    assert resp.json()[0]["type"] == "income"


async def test_manual_entry_rejects_unknown_category(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {
                    "date": "2026-01-01",
                    "amount": "100",
                    "category_id": "00000000-0000-0000-0000-000000000000",
                }
            ],
        },
    )
    assert resp.status_code == 400


async def test_manual_entry_requires_type_or_category(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [{"date": "2026-01-01", "amount": "100"}],
        },
    )
    assert resp.status_code == 422


async def test_manual_entry_rejects_non_positive_amount(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {"date": "2026-01-01", "amount": "0", "category_id": cats["Rent"]["id"]}
            ],
        },
    )
    assert resp.status_code == 422


async def test_manual_entry_cannot_target_another_users_company(client: AsyncClient):
    headers_a = await _auth(client, "a@example.com")
    cid_a = await _company(client, headers_a)
    cats = await _categories(client, headers_a, cid_a)
    headers_b = await _auth(client, "b@example.com")
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers_b,
        json={
            "company_id": cid_a,
            "transactions": [
                {"date": "2026-01-01", "amount": "100", "category_id": cats["Rent"]["id"]}
            ],
        },
    )
    assert resp.status_code == 404


async def test_list_transactions_includes_manual_entries(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {"date": "2026-01-15", "amount": "1000", "category_id": cats["Revenue"]["id"]}
            ],
        },
    )
    listing = await client.get(
        "/api/v1/transactions", headers=headers, params={"company_id": cid}
    )
    assert listing.status_code == 200
    body = listing.json()
    assert len(body) == 1
    assert body[0]["source"] == "manual"
