"""Endpoint tests for revenue/expense totals + monthly cash flow (task 4.2,
FR-3.2/FR-3.3): GET /financial/summary and GET /financial/cash-flow."""

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


async def _signup(client: AsyncClient, email: str) -> dict:
    token = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": email, "password": "sup3r-secret"},
        )
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


async def _company(client: AsyncClient, headers: dict) -> str:
    return (
        await client.post("/api/v1/companies", headers=headers, json={"name": "Acme"})
    ).json()["id"]


async def _seed(client: AsyncClient, headers: dict, cid: str) -> None:
    """Two months of income + expense via upload."""
    csv = (
        b"date,amount,description,type\n"
        b"2026-01-10,5000,Jan sale,income\n"
        b"2026-01-20,2000,Jan rent,expense\n"
        b"2026-02-05,7000,Feb sale,income\n"
        b"2026-02-15,3000,Feb rent,expense\n"
    )
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201


async def test_summary_all_time(client: AsyncClient):
    headers = await _signup(client, "a@example.com")
    cid = await _company(client, headers)
    await _seed(client, headers, cid)

    resp = await client.get(
        "/api/v1/financial/summary", headers=headers, params={"company_id": cid}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_income"] == "12000.00"  # 5000 + 7000
    assert body["total_expenses"] == "5000.00"  # 2000 + 3000
    assert body["net"] == "7000.00"
    assert body["income_count"] == 2
    assert body["expense_count"] == 2
    assert body["start_date"] is None and body["end_date"] is None


async def test_summary_date_range_filters(client: AsyncClient):
    headers = await _signup(client, "b@example.com")
    cid = await _company(client, headers)
    await _seed(client, headers, cid)

    # January only.
    resp = await client.get(
        "/api/v1/financial/summary",
        headers=headers,
        params={"company_id": cid, "start_date": "2026-01-01", "end_date": "2026-01-31"},
    )
    body = resp.json()
    assert body["total_income"] == "5000.00"
    assert body["total_expenses"] == "2000.00"
    assert body["net"] == "3000.00"
    assert body["income_count"] == 1 and body["expense_count"] == 1


async def test_summary_empty_company_is_zero(client: AsyncClient):
    headers = await _signup(client, "c@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/summary", headers=headers, params={"company_id": cid}
    )
    body = resp.json()
    assert body["total_income"] == "0.00"
    assert body["total_expenses"] == "0.00"
    assert body["net"] == "0.00"


async def test_cash_flow_monthly_buckets(client: AsyncClient):
    headers = await _signup(client, "d@example.com")
    cid = await _company(client, headers)
    await _seed(client, headers, cid)

    resp = await client.get(
        "/api/v1/financial/cash-flow", headers=headers, params={"company_id": cid}
    )
    assert resp.status_code == 200
    months = resp.json()["months"]
    assert [m["month"] for m in months] == ["2026-01", "2026-02"]
    assert months[0]["inflow"] == "5000.00"
    assert months[0]["outflow"] == "2000.00"
    assert months[0]["net"] == "3000.00"
    assert months[1]["inflow"] == "7000.00"
    assert months[1]["outflow"] == "3000.00"
    assert months[1]["net"] == "4000.00"


async def test_cash_flow_range_filters(client: AsyncClient):
    headers = await _signup(client, "e@example.com")
    cid = await _company(client, headers)
    await _seed(client, headers, cid)

    resp = await client.get(
        "/api/v1/financial/cash-flow",
        headers=headers,
        params={"company_id": cid, "start_date": "2026-02-01"},
    )
    months = resp.json()["months"]
    assert [m["month"] for m in months] == ["2026-02"]


async def test_bad_range_is_400(client: AsyncClient):
    headers = await _signup(client, "f@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/summary",
        headers=headers,
        params={"company_id": cid, "start_date": "2026-03-01", "end_date": "2026-01-01"},
    )
    assert resp.status_code == 400


async def test_requires_auth(client: AsyncClient):
    headers = await _signup(client, "g@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/summary", params={"company_id": cid}
    )
    assert resp.status_code == 401


async def test_other_users_company_is_404(client: AsyncClient):
    owner = await _signup(client, "owner@example.com")
    cid = await _company(client, owner)
    intruder = await _signup(client, "intruder@example.com")

    summary = await client.get(
        "/api/v1/financial/summary", headers=intruder, params={"company_id": cid}
    )
    cash = await client.get(
        "/api/v1/financial/cash-flow", headers=intruder, params={"company_id": cid}
    )
    assert summary.status_code == 404
    assert cash.status_code == 404
