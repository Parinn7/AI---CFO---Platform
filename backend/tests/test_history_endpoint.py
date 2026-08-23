"""Endpoint tests for the historical/12-month view (task 4.4, FR-3.5/FR-4.6):
GET /financial/history."""

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
from app.financial_engine import models as _fin_models  # noqa: F401


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


async def _upload(client: AsyncClient, headers: dict, cid: str, csv: bytes) -> None:
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201


async def test_history_anchors_to_latest_data_month(client: AsyncClient):
    headers = await _signup(client, "hist@example.com")
    cid = await _company(client, headers)
    # Data in Jan and Mar 2026; latest is March → anchor without end_month.
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2026-01-10,5000,Jan sale,income\n"
        b"2026-01-20,2000,Jan rent,expense\n"
        b"2026-03-05,8000,Mar sale,income\n",
    )
    resp = await client.get(
        "/api/v1/financial/history",
        headers=headers,
        params={"company_id": cid, "months": 3},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["end_month"] == "2026-03"  # latest data month
    assert body["num_months"] == 3
    assert [m["month"] for m in body["months"]] == ["2026-01", "2026-02", "2026-03"]
    jan, feb, mar = body["months"]
    assert jan["net_cash_flow"] == "3000.00"
    assert jan["margin_pct"] == "60.00"
    assert feb["revenue"] == "0.00"  # zero-filled gap
    assert feb["margin_pct"] is None
    assert mar["revenue"] == "8000.00"


async def test_history_explicit_end_month(client: AsyncClient):
    headers = await _signup(client, "hist2@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n2026-02-10,4000,Feb sale,income\n",
    )
    resp = await client.get(
        "/api/v1/financial/history",
        headers=headers,
        params={"company_id": cid, "months": 2, "end_month": "2026-02"},
    )
    body = resp.json()
    assert body["end_month"] == "2026-02"
    assert [m["month"] for m in body["months"]] == ["2026-01", "2026-02"]
    assert body["months"][1]["revenue"] == "4000.00"


async def test_history_no_data_returns_zero_filled_series(client: AsyncClient):
    headers = await _signup(client, "hist3@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/history",
        headers=headers,
        params={"company_id": cid, "months": 12, "end_month": "2026-06"},
    )
    body = resp.json()
    assert len(body["months"]) == 12
    assert body["months"][0]["month"] == "2025-07"
    assert body["months"][-1]["month"] == "2026-06"
    assert all(m["revenue"] == "0.00" for m in body["months"])


async def test_history_bad_end_month_is_400(client: AsyncClient):
    headers = await _signup(client, "hist4@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/history",
        headers=headers,
        params={"company_id": cid, "end_month": "2026-13"},
    )
    assert resp.status_code == 400


async def test_history_out_of_bounds_months_is_422(client: AsyncClient):
    headers = await _signup(client, "hist5@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/history",
        headers=headers,
        params={"company_id": cid, "months": 0},
    )
    assert resp.status_code == 422  # Query ge=1


async def test_history_requires_auth(client: AsyncClient):
    headers = await _signup(client, "hist6@example.com")
    cid = await _company(client, headers)
    resp = await client.get(
        "/api/v1/financial/history", params={"company_id": cid}
    )
    assert resp.status_code == 401


async def test_history_other_users_company_is_404(client: AsyncClient):
    owner = await _signup(client, "owner3@example.com")
    cid = await _company(client, owner)
    intruder = await _signup(client, "intruder3@example.com")
    resp = await client.get(
        "/api/v1/financial/history", headers=intruder, params={"company_id": cid}
    )
    assert resp.status_code == 404
