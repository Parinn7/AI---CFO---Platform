"""End-to-end tests for editing/deleting transactions (task 3.5, FR-2.5).

Same in-memory SQLite + get_db override + seeded default categories as the other
transaction tests.
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
    return {c["name"]: c for c in resp.json()}


async def _make_txn(client: AsyncClient, headers: dict, cid: str, cats: dict) -> dict:
    resp = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {
                    "date": "2026-01-10",
                    "amount": "1000",
                    "category_id": cats["Rent"]["id"],
                    "description": "Original",
                }
            ],
        },
    )
    return resp.json()["created"][0]


async def test_edit_transaction_fields(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)

    resp = await client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=headers,
        json={"amount": "1500", "description": "Updated rent"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert float(body["amount"]) == 1500.0
    assert body["description"] == "Updated rent"
    # Untouched fields preserved.
    assert body["date"] == "2026-01-10"
    assert body["type"] == "expense"


async def test_edit_category_does_not_change_type(client: AsyncClient):
    """schema.md §4: type stays fixed across a category change unless sent."""
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)  # Rent → expense

    resp = await client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=headers,
        json={"category_id": cats["Revenue"]["id"]},  # Revenue is income
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["category_id"] == cats["Revenue"]["id"]
    assert body["type"] == "expense"  # unchanged


async def test_edit_type_explicitly(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)

    resp = await client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=headers,
        json={"type": "income"},
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "income"


async def test_edit_rejects_bad_amount(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)

    resp = await client.patch(
        f"/api/v1/transactions/{txn['id']}", headers=headers, json={"amount": "0"}
    )
    assert resp.status_code == 422


async def test_edit_rejects_unknown_category(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)

    resp = await client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=headers,
        json={"category_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert resp.status_code == 400


async def test_delete_transaction(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    cats = await _categories(client, headers, cid)
    txn = await _make_txn(client, headers, cid, cats)

    resp = await client.delete(f"/api/v1/transactions/{txn['id']}", headers=headers)
    assert resp.status_code == 204

    listing = await client.get(
        "/api/v1/transactions", headers=headers, params={"company_id": cid}
    )
    assert listing.json() == []


async def test_cannot_edit_another_users_transaction(client: AsyncClient):
    headers_a = await _auth(client, "a@example.com")
    cid_a = await _company(client, headers_a)
    cats = await _categories(client, headers_a, cid_a)
    txn = await _make_txn(client, headers_a, cid_a, cats)

    headers_b = await _auth(client, "b@example.com")
    patch = await client.patch(
        f"/api/v1/transactions/{txn['id']}",
        headers=headers_b,
        json={"amount": "9999"},
    )
    assert patch.status_code == 404
    delete = await client.delete(
        f"/api/v1/transactions/{txn['id']}", headers=headers_b
    )
    assert delete.status_code == 404


async def test_edit_requires_auth(client: AsyncClient):
    resp = await client.patch(
        "/api/v1/transactions/00000000-0000-0000-0000-000000000000",
        json={"amount": "1"},
    )
    assert resp.status_code == 401
