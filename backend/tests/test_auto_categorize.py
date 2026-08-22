"""End-to-end tests for auto-categorization (task 4.1): the explicit endpoint
plus inline categorization during upload.
"""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import app
from app.transactions.categories import DEFAULT_CATEGORIES
from app.transactions.models import Category, Transaction

from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401


@pytest_asyncio.fixture
async def ctx() -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
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
        yield ac, session_factory
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


async def test_auto_categorize_endpoint(ctx):
    client, session_factory = ctx
    headers = await _auth(client)
    cid = await _company(client, headers)

    # Seed uncategorized transactions directly.
    async with session_factory() as s:
        s.add_all(
            [
                Transaction(
                    company_id=uuid.UUID(cid), source="upload",
                    date=dt.date(2026, 1, 1), amount=Decimal("25000"),
                    type="expense", description="Monthly office rent", category_id=None,
                ),
                Transaction(
                    company_id=uuid.UUID(cid), source="manual",
                    date=dt.date(2026, 1, 2), amount=Decimal("50000"),
                    type="income", description="", category_id=None,
                ),
                Transaction(
                    company_id=uuid.UUID(cid), source="upload",
                    date=dt.date(2026, 1, 3), amount=Decimal("999"),
                    type="expense", description="mystery blob", category_id=None,
                ),
            ]
        )
        await s.commit()

    resp = await client.post(
        "/api/v1/transactions/auto-categorize",
        headers=headers,
        json={"company_id": cid},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["categorized"] == 2  # rent + income→Revenue
    assert body["uncategorized_remaining"] == 1  # 'mystery blob' unmatched

    txns = (
        await client.get(
            "/api/v1/transactions", headers=headers, params={"company_id": cid}
        )
    ).json()
    cats = {
        c["name"]: c["id"]
        for c in (
            await client.get(
                "/api/v1/categories", headers=headers, params={"company_id": cid}
            )
        ).json()
    }
    by_desc = {t["description"]: t for t in txns}
    assert by_desc["Monthly office rent"]["category_id"] == cats["Rent"]
    assert by_desc[""]["category_id"] == cats["Revenue"]
    assert by_desc["mystery blob"]["category_id"] is None


async def test_auto_categorize_requires_ownership(ctx):
    client, _ = ctx
    headers_a = await _auth(client, "a@example.com")
    cid_a = await _company(client, headers_a)
    headers_b = await _auth(client, "b@example.com")
    resp = await client.post(
        "/api/v1/transactions/auto-categorize",
        headers=headers_b,
        json={"company_id": cid_a},
    )
    assert resp.status_code == 404


async def test_upload_auto_categorizes_uncategorized_rows(ctx):
    client, _ = ctx
    headers = await _auth(client)
    cid = await _company(client, headers)
    # No category column; a type column keeps direction correct.
    csv = (
        b"date,amount,description,type\n"
        b"2026-01-05,25000,Monthly rent,expense\n"
        b"2026-01-06,4000,AWS subscription,expense\n"
        b"2026-01-07,90000,Client invoice,income\n"
    )
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201
    cats = {
        c["name"]: c["id"]
        for c in (
            await client.get(
                "/api/v1/categories", headers=headers, params={"company_id": cid}
            )
        ).json()
    }
    by_desc = {t["description"]: t for t in resp.json()["transactions"]}
    assert by_desc["Monthly rent"]["category_id"] == cats["Rent"]
    assert by_desc["AWS subscription"]["category_id"] == cats["Software/Tools"]
    assert by_desc["Client invoice"]["category_id"] == cats["Revenue"]
