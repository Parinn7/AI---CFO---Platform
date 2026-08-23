"""Endpoint test for anomaly detection (task 4.5, FR-3.6):
POST /transactions/detect-anomalies — flags anomalous expenses via the
category-month spike rule and reports counts."""

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


async def test_detect_flags_the_spike_only(client: AsyncClient):
    headers = await _signup(client, "anom@example.com")
    cid = await _company(client, headers)
    # Rent steady ~10k Jan–Mar, then 50k spike in Apr; plus a normal income row.
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,category,type\n"
        b"2026-01-15,10000,Rent,Rent,expense\n"
        b"2026-02-15,10000,Rent,Rent,expense\n"
        b"2026-03-15,10000,Rent,Rent,expense\n"
        b"2026-04-15,50000,Rent,Rent,expense\n"
        b"2026-04-20,90000,Big sale,Revenue,income\n",
    )

    resp = await client.post(
        "/api/v1/transactions/detect-anomalies",
        headers=headers,
        json={"company_id": cid},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["flagged"] == 1
    assert body["expenses_scanned"] == 4  # income not scanned

    # The April rent row is flagged; nothing else is.
    txns = (
        await client.get(
            "/api/v1/transactions", headers=headers, params={"company_id": cid}
        )
    ).json()
    flagged = [t for t in txns if t["is_flagged_anomaly"]]
    assert len(flagged) == 1
    assert flagged[0]["date"] == "2026-04-15"
    assert flagged[0]["amount"] == "50000.00"


async def test_detect_is_idempotent_and_clears_stale_flags(client: AsyncClient):
    headers = await _signup(client, "anom2@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,category,type\n"
        b"2026-01-15,10000,Rent,Rent,expense\n"
        b"2026-02-15,10000,Rent,Rent,expense\n"
        b"2026-03-15,10000,Rent,Rent,expense\n"
        b"2026-04-15,50000,Rent,Rent,expense\n",
    )
    first = await client.post(
        "/api/v1/transactions/detect-anomalies", headers=headers, json={"company_id": cid}
    )
    assert first.json()["flagged"] == 1
    # Running again yields the same result (idempotent).
    second = await client.post(
        "/api/v1/transactions/detect-anomalies", headers=headers, json={"company_id": cid}
    )
    assert second.json()["flagged"] == 1

    # Delete the spike → the April anomaly should clear on re-detect.
    txns = (
        await client.get(
            "/api/v1/transactions", headers=headers, params={"company_id": cid}
        )
    ).json()
    spike = next(t for t in txns if t["amount"] == "50000.00")
    await client.delete(f"/api/v1/transactions/{spike['id']}", headers=headers)
    third = await client.post(
        "/api/v1/transactions/detect-anomalies", headers=headers, json={"company_id": cid}
    )
    assert third.json()["flagged"] == 0


async def test_detect_requires_auth(client: AsyncClient):
    headers = await _signup(client, "anom3@example.com")
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/transactions/detect-anomalies", json={"company_id": cid}
    )
    assert resp.status_code == 401


async def test_detect_other_users_company_is_404(client: AsyncClient):
    owner = await _signup(client, "owner4@example.com")
    cid = await _company(client, owner)
    intruder = await _signup(client, "intruder4@example.com")
    resp = await client.post(
        "/api/v1/transactions/detect-anomalies", headers=intruder, json={"company_id": cid}
    )
    assert resp.status_code == 404
