"""Endpoint tests for KPI snapshot generation (task 4.3, FR-4.1–4.5):
POST /financial/kpi-snapshots and GET /financial/kpi-snapshots."""

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


async def test_snapshot_burning_company(client: AsyncClient):
    headers = await _signup(client, "burn@example.com")
    cid = await _company(client, headers)
    # December (prior window): revenue 20k. January: revenue 30k, expenses 60k.
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2025-12-10,20000,Dec sale,income\n"
        b"2026-01-10,30000,Jan sale,income\n"
        b"2026-01-20,60000,Jan spend,expense\n",
    )
    resp = await client.post(
        "/api/v1/financial/kpi-snapshots",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_revenue"] == "30000.00"
    assert body["total_expenses"] == "60000.00"
    assert body["net_cash_flow"] == "-30000.00"
    assert body["burn_rate"] == "30000.00"  # (60k−30k)/1 month
    # cash_on_hand = cumulative to Jan 31 = 20k + 30k − 60k = −10k → no runway.
    assert body["runway_months"] is None
    assert body["gross_margin_pct"] == "-100.00"
    assert body["operating_margin_pct"] == body["gross_margin_pct"]
    # growth vs Dec (equal-length prior window): (30k−20k)/20k×100 = 50%.
    assert body["revenue_growth_pct"] == "50.00"


async def test_snapshot_profitable_company_has_runway(client: AsyncClient):
    headers = await _signup(client, "profit@example.com")
    cid = await _company(client, headers)
    # One profitable month: revenue 100k, expenses 60k → net +40k (also cash).
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2026-03-05,100000,Mar sale,income\n"
        b"2026-03-15,60000,Mar spend,expense\n",
    )
    resp = await client.post(
        "/api/v1/financial/kpi-snapshots",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-03-01",
            "period_end": "2026-03-31",
        },
    )
    body = resp.json()
    assert body["burn_rate"] == "-40000.00"  # not burning
    assert body["runway_months"] is None  # burn ≤ 0
    assert body["gross_margin_pct"] == "40.00"
    assert body["revenue_growth_pct"] is None  # no Feb data


async def test_snapshot_is_persisted_and_listed(client: AsyncClient):
    headers = await _signup(client, "list@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n2026-01-10,5000,Jan sale,income\n",
    )
    for period in (("2026-01-01", "2026-01-31"), ("2026-02-01", "2026-02-28")):
        await client.post(
            "/api/v1/financial/kpi-snapshots",
            headers=headers,
            json={"company_id": cid, "period_start": period[0], "period_end": period[1]},
        )
    listed = await client.get(
        "/api/v1/financial/kpi-snapshots", headers=headers, params={"company_id": cid}
    )
    assert listed.status_code == 200
    snaps = listed.json()
    assert len(snaps) == 2
    # Most recent period first.
    assert snaps[0]["period_end"] == "2026-02-28"


async def test_bad_period_is_422(client: AsyncClient):
    headers = await _signup(client, "badperiod@example.com")
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/financial/kpi-snapshots",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-03-01",
            "period_end": "2026-01-01",
        },
    )
    assert resp.status_code == 422  # schema validator rejects start > end


async def test_requires_auth(client: AsyncClient):
    headers = await _signup(client, "noauth@example.com")
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/financial/kpi-snapshots",
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        },
    )
    assert resp.status_code == 401


async def test_other_users_company_is_404(client: AsyncClient):
    owner = await _signup(client, "owner2@example.com")
    cid = await _company(client, owner)
    intruder = await _signup(client, "intruder2@example.com")
    gen = await client.post(
        "/api/v1/financial/kpi-snapshots",
        headers=intruder,
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
        },
    )
    lst = await client.get(
        "/api/v1/financial/kpi-snapshots", headers=intruder, params={"company_id": cid}
    )
    assert gen.status_code == 404
    assert lst.status_code == 404
