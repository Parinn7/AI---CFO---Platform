"""FR-2.6 verification (task 3.6): manually-entered data flows into downstream
aggregation identically to uploaded data, with no separate "conversion" step.

Both paths write to the same `transactions` table, differing only in `source`
(and a null `upload_batch_id` for manual). Nothing downstream branches on
`source`, so a source-agnostic aggregation — exactly what the Financial Engine
(Phase 4) and reports (Phase 9) will do — treats them the same. This test locks
that guarantee in at the data layer; KPI/dashboard/report *output* equivalence is
re-confirmed as those layers are built (see 9.5 for reports).
"""

from collections.abc import AsyncGenerator
from decimal import Decimal

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


async def test_manual_and_upload_transactions_aggregate_identically(
    client: AsyncClient,
):
    token = (
        await client.post(
            "/api/v1/auth/signup",
            json={"email": "a@example.com", "password": "sup3r-secret"},
        )
    ).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    cid = (
        await client.post("/api/v1/companies", headers=headers, json={"name": "Acme"})
    ).json()["id"]
    cats = {
        c["name"]: c
        for c in (
            await client.get(
                "/api/v1/categories", headers=headers, params={"company_id": cid}
            )
        ).json()
    }

    # Manual entry: ₹5,000 revenue.
    manual = await client.post(
        "/api/v1/transactions",
        headers=headers,
        json={
            "company_id": cid,
            "transactions": [
                {
                    "date": "2026-01-10",
                    "amount": "5000",
                    "category_id": cats["Revenue"]["id"],
                    "description": "Manual sale",
                }
            ],
        },
    )
    assert manual.status_code == 201

    # Upload: ₹7,000 income + ₹2,000 expense (no conversion step in between).
    csv = (
        b"date,amount,description,type\n"
        b"2026-01-15,7000,Uploaded sale,income\n"
        b"2026-01-16,2000,Bus fare,expense\n"
    )
    up = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert up.status_code == 201

    # One source-agnostic list feeds any downstream aggregation.
    txns = (
        await client.get(
            "/api/v1/transactions", headers=headers, params={"company_id": cid}
        )
    ).json()

    # Both sources are present in the same feed, no "convert manual → doc" step.
    assert {t["source"] for t in txns} == {"manual", "upload"}

    # Aggregating by type (the KPI engine's job) counts manual + upload alike.
    income = sum(Decimal(t["amount"]) for t in txns if t["type"] == "income")
    expense = sum(Decimal(t["amount"]) for t in txns if t["type"] == "expense")
    assert income == Decimal("12000.00")  # 5000 manual + 7000 upload
    assert expense == Decimal("2000.00")

    # The manual and uploaded income rows are structurally identical bar the
    # provenance fields (source, upload_batch_id) — so nothing downstream can
    # tell them apart on anything that affects the numbers.
    manual_row = next(t for t in txns if t["source"] == "manual")
    upload_row = next(
        t for t in txns if t["source"] == "upload" and t["type"] == "income"
    )
    provenance = {"source", "upload_batch_id", "id", "created_at", "date",
                  "description", "amount", "category_id"}
    assert set(manual_row) == set(upload_row)  # same shape
    for field in set(manual_row) - provenance:
        # Non-provenance fields (type, is_flagged_anomaly, company_id) match.
        assert manual_row[field] == upload_row[field]
