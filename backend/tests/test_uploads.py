"""End-to-end tests for the CSV/XLSX upload flow (task 3.2).

In-memory SQLite + get_db override, same as the other endpoint tests. The
fixture seeds the default categories (create_all doesn't run migration 0002) so
category matching + type resolution are exercised.
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

    # Seed system-default categories (company_id NULL).
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
        await client.post(
            "/api/v1/companies", headers=headers, json={"name": "Acme"}
        )
    ).json()["id"]


def _upload(cid: str, content: bytes, name: str = "t.csv"):
    mime = "text/csv" if name.endswith(".csv") else (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    return {"data": {"company_id": cid}, "files": {"file": (name, content, mime)}}


async def test_upload_maps_categories_and_resolves_type(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    csv = (
        b"Date,Description,Amount,Category\n"
        b"2026-01-05,Client invoice,120000,Revenue\n"
        b"2026-01-06,Office rent,25000,Rent\n"
    )
    resp = await client.post("/api/v1/uploads", headers=headers, **_upload(cid, csv))
    assert resp.status_code == 201
    body = resp.json()
    assert body["batch"]["status"] == "completed"
    assert body["batch"]["row_count"] == 2
    assert body["batch"]["error_log"] is None

    txns = {t["description"]: t for t in body["transactions"]}
    # Type comes from the matched category; amount is a positive magnitude.
    assert txns["Client invoice"]["type"] == "income"
    assert float(txns["Client invoice"]["amount"]) == 120000.0
    assert txns["Client invoice"]["category_id"] is not None
    assert txns["Office rent"]["type"] == "expense"
    assert txns["Office rent"]["source"] == "upload"


async def test_type_inferred_from_sign_when_no_hints(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    csv = b"date,amount,description\n2026-02-01,5000,in\n2026-02-02,-800,out\n"
    resp = await client.post("/api/v1/uploads", headers=headers, **_upload(cid, csv))
    txns = resp.json()["transactions"]
    by_desc = {t["description"]: t for t in txns}
    assert by_desc["in"]["type"] == "income"
    assert by_desc["out"]["type"] == "expense"
    # Stored as positive magnitude regardless of sign.
    assert float(by_desc["out"]["amount"]) == 800.0


async def test_bad_rows_recorded_in_error_log(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    csv = (
        b"date,amount\n"
        b"2026-01-01,100\n"
        b",200\n"                # missing date
        b"2026-01-03,oops\n"     # bad amount
    )
    resp = await client.post("/api/v1/uploads", headers=headers, **_upload(cid, csv))
    batch = resp.json()["batch"]
    assert batch["row_count"] == 1
    assert batch["error_log"] is not None
    assert "Row 3" in batch["error_log"] and "Row 4" in batch["error_log"]


async def test_unsupported_file_type_is_400(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/uploads", headers=headers, **_upload(cid, b"x", name="data.txt")
    )
    assert resp.status_code == 400


async def test_missing_columns_is_400(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    resp = await client.post(
        "/api/v1/uploads", headers=headers, **_upload(cid, b"foo,bar\n1,2\n")
    )
    assert resp.status_code == 400


async def test_upload_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/uploads", **_upload("00000000-0000-0000-0000-000000000000", b"x")
    )
    assert resp.status_code == 401


async def test_cannot_upload_to_another_users_company(client: AsyncClient):
    headers_a = await _auth(client, "a@example.com")
    cid_a = await _company(client, headers_a)
    headers_b = await _auth(client, "b@example.com")
    csv = b"date,amount\n2026-01-01,100\n"
    resp = await client.post(
        "/api/v1/uploads", headers=headers_b, **_upload(cid_a, csv)
    )
    assert resp.status_code == 404


async def test_list_and_get_batch(client: AsyncClient):
    headers = await _auth(client)
    cid = await _company(client, headers)
    csv = b"date,amount\n2026-01-01,100\n"
    batch_id = (
        await client.post("/api/v1/uploads", headers=headers, **_upload(cid, csv))
    ).json()["batch"]["id"]

    listing = await client.get(
        "/api/v1/uploads", headers=headers, params={"company_id": cid}
    )
    assert listing.status_code == 200
    assert [b["id"] for b in listing.json()] == [batch_id]

    detail = await client.get(f"/api/v1/uploads/{batch_id}", headers=headers)
    assert detail.status_code == 200
    assert len(detail.json()["transactions"]) == 1


async def test_cannot_get_another_users_batch(client: AsyncClient):
    headers_a = await _auth(client, "a@example.com")
    cid_a = await _company(client, headers_a)
    csv = b"date,amount\n2026-01-01,100\n"
    batch_id = (
        await client.post("/api/v1/uploads", headers=headers_a, **_upload(cid_a, csv))
    ).json()["batch"]["id"]

    headers_b = await _auth(client, "b@example.com")
    resp = await client.get(f"/api/v1/uploads/{batch_id}", headers=headers_b)
    assert resp.status_code == 404
