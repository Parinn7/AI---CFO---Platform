"""Endpoint tests for the Monthly Financial Report (task 8.1, FR-7.1):
GET /reports/monthly.

The property worth pinning hardest is that a report **quotes** the engine
rather than recomputing it — so the assertions compare the report's figures
against the `kpi_snapshots` row and the dashboard endpoints, not just against
hand-computed constants.
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


async def _company(client: AsyncClient, headers: dict, name: str = "Acme") -> str:
    return (
        await client.post(
            "/api/v1/companies", headers=headers, json={"name": name}
        )
    ).json()["id"]


async def _upload(client: AsyncClient, headers: dict, cid: str, csv: bytes) -> None:
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201


# June: revenue 200k, payroll 90k, rent 30k.
# July: revenue 300k, payroll 150k, rent 30k, marketing 20k.
TWO_MONTHS = (
    b"date,amount,description,type\n"
    b"2026-06-05,200000,Client invoice,income\n"
    b"2026-06-07,90000,Salaries for June,expense\n"
    b"2026-06-10,30000,Office rent,expense\n"
    b"2026-07-05,300000,Client invoice,income\n"
    b"2026-07-07,150000,Salaries for July,expense\n"
    b"2026-07-10,30000,Office rent,expense\n"
    b"2026-07-20,20000,Google Ads campaign,expense\n"
)


async def _report(client: AsyncClient, headers: dict, cid: str, month=None) -> dict:
    query = f"?company_id={cid}" + (f"&month={month}" if month else "")
    resp = await client.get(f"/api/v1/reports/monthly{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_report_summarises_revenue_expenses_cash_flow_and_kpis(
    client: AsyncClient,
):
    """FR-7.1's four required subjects, for one calendar month."""
    headers = await _signup(client, "monthly@example.com")
    cid = await _company(client, headers, "Northwind")
    await _upload(client, headers, cid, TWO_MONTHS)

    body = await _report(client, headers, cid, "2026-07")

    assert body["report_type"] == "monthly"
    assert body["company"]["name"] == "Northwind"
    assert body["month"] == "2026-07"
    assert body["period_start"] == "2026-07-01"
    assert body["period_end"] == "2026-07-31"

    kpis = body["kpis"]
    assert kpis["total_revenue"] == "300000.00"
    assert kpis["total_expenses"] == "200000.00"
    assert kpis["net_cash_flow"] == "100000.00"
    assert kpis["burn_rate"] == "-100000.00"  # a surplus month, not a burn
    assert kpis["runway_months"] is None  # not burning → undefined
    assert kpis["gross_margin_pct"] == "33.33"
    # Growth is against June (the equal-length preceding window): 200k → 300k.
    assert kpis["revenue_growth_pct"] == "50.00"

    # Cash flow: closing cash is cumulative through 31 July, opening cash ₹0.
    assert body["closing_cash"] == "180000.00"  # June net 80k + July net 100k
    assert body["transaction_count"] == 4
    assert body["income_count"] == 1
    assert body["expense_count"] == 3


async def test_defaults_to_the_latest_month_with_data(client: AsyncClient):
    """"This month" is empty for books kept in arrears; the last real month is
    the useful default."""
    headers = await _signup(client, "latest@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    assert (await _report(client, headers, cid))["month"] == "2026-07"


async def test_kpis_are_the_stored_snapshot_not_a_second_calculation(
    client: AsyncClient,
):
    """The report must quote the same `kpi_snapshots` row the dashboard reads —
    architecture §4.1. Figures that merely agree today can drift; one shared row
    cannot."""
    headers = await _signup(client, "snapshot@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    report = await _report(client, headers, cid, "2026-07")
    stored = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()

    july = [s for s in stored if s["period_start"] == "2026-07-01"]
    assert len(july) == 1, "the report should reuse one snapshot, not mint rows"
    assert july[0]["id"] == report["kpis"]["id"]

    # Regenerating must not create a second row for the same month.
    await _report(client, headers, cid, "2026-07")
    again = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    assert len([s for s in again if s["period_start"] == "2026-07-01"]) == 1


async def test_category_lines_add_up_to_the_totals(client: AsyncClient):
    headers = await _signup(client, "lines@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    body = await _report(client, headers, cid, "2026-07")
    lines = body["categories"]

    # Income first, then expenses largest-first.
    assert [line["name"] for line in lines] == [
        "Revenue",
        "Payroll",
        "Rent",
        "Marketing",
    ]
    expenses = [line for line in lines if line["type"] == "expense"]
    assert sum(float(line["total"]) for line in expenses) == float(
        body["kpis"]["total_expenses"]
    )
    payroll = next(line for line in lines if line["name"] == "Payroll")
    assert payroll["total"] == "150000.00"
    assert payroll["share_pct"] == "75.00"  # of expenses, not of all money moved
    assert payroll["transaction_count"] == 1


async def test_comparison_against_the_previous_month(client: AsyncClient):
    headers = await _signup(client, "compare@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    comparison = (await _report(client, headers, cid, "2026-07"))["comparison"]
    assert comparison["month"] == "2026-06"
    assert comparison["has_data"] is True
    assert comparison["total_revenue"] == "200000.00"
    assert comparison["revenue_change"] == "100000.00"
    assert comparison["expenses_change"] == "80000.00"  # 200k − 120k
    assert comparison["net_change"] == "20000.00"  # 100k − 80k


async def test_missing_previous_month_is_flagged_not_silently_zero(
    client: AsyncClient,
):
    """June has no May before it. The changes are differences against zero,
    which is true but means "no record", so the flag has to say so."""
    headers = await _signup(client, "nomay@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    comparison = (await _report(client, headers, cid, "2026-06"))["comparison"]
    assert comparison["month"] == "2026-05"
    assert comparison["has_data"] is False
    assert comparison["total_revenue"] == "0.00"


async def test_trend_is_six_continuous_months_ending_at_the_report_month(
    client: AsyncClient,
):
    headers = await _signup(client, "trend@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    trend = (await _report(client, headers, cid, "2026-07"))["trend"]
    assert [m["month"] for m in trend] == [
        "2026-02",
        "2026-03",
        "2026-04",
        "2026-05",
        "2026-06",
        "2026-07",
    ]
    # Empty months are zero-filled, not omitted (FR-4.6).
    assert trend[0]["revenue"] == "0.00"
    assert trend[-1]["revenue"] == "300000.00"


async def test_anomalies_flagged_in_the_month_are_listed(client: AsyncClient):
    """A report surfaces what needs attention, not only what happened (FR-3.6).

    Four flat months of ₹20k marketing, then ₹200k — a spike against the
    trailing 3-month average."""
    headers = await _signup(client, "anomaly@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2026-01-10,20000,Google Ads,expense\n"
        b"2026-02-10,20000,Google Ads,expense\n"
        b"2026-03-10,20000,Google Ads,expense\n"
        b"2026-04-10,200000,Google Ads blowout,expense\n",
    )
    resp = await client.post(
        "/api/v1/transactions/detect-anomalies",
        headers=headers,
        json={"company_id": cid},
    )
    assert resp.json()["flagged"] == 1

    body = await _report(client, headers, cid, "2026-04")
    assert len(body["anomalies"]) == 1
    assert body["anomalies"][0]["amount"] == "200000.00"
    assert body["anomalies"][0]["category_name"] == "Marketing"

    # A quiet month reports no anomalies rather than the company's whole list.
    assert (await _report(client, headers, cid, "2026-03"))["anomalies"] == []


async def test_month_with_no_transactions_reports_honest_zeros(client: AsyncClient):
    """A quiet month is a real finding. Undefined ratios stay null rather than
    becoming a 0% that reads like a measurement."""
    headers = await _signup(client, "quiet@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    body = await _report(client, headers, cid, "2026-05")
    assert body["transaction_count"] == 0
    assert body["kpis"]["total_revenue"] == "0.00"
    assert body["kpis"]["gross_margin_pct"] is None
    assert body["kpis"]["revenue_growth_pct"] is None
    assert body["categories"] == []


async def test_company_with_no_data_at_all_is_404(client: AsyncClient):
    headers = await _signup(client, "empty@example.com")
    cid = await _company(client, headers)

    resp = await client.get(f"/api/v1/reports/monthly?company_id={cid}", headers=headers)
    assert resp.status_code == 404
    assert "No financial data" in resp.json()["detail"]


async def test_bad_month_is_400(client: AsyncClient):
    headers = await _signup(client, "badmonth@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, TWO_MONTHS)

    for bad in ("2026-13", "July", "26-07", "2026-7"):
        resp = await client.get(
            f"/api/v1/reports/monthly?company_id={cid}&month={bad}", headers=headers
        )
        assert resp.status_code == 400, bad


async def test_report_requires_auth_and_ownership(client: AsyncClient):
    owner = await _signup(client, "owner@example.com")
    cid = await _company(client, owner)
    await _upload(client, owner, cid, TWO_MONTHS)

    anon = await client.get(f"/api/v1/reports/monthly?company_id={cid}")
    assert anon.status_code == 401

    intruder = await _signup(client, "intruder@example.com")
    resp = await client.get(
        f"/api/v1/reports/monthly?company_id={cid}", headers=intruder
    )
    # 404, not 403 — the endpoint doesn't confirm the company exists.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Company not found."


async def test_manual_entries_report_identically_to_uploads(client: AsyncClient):
    """FR-2.6 through the reporting layer (groundwork for task 8.5): the same
    figures entered by hand must produce the same report."""
    uploaded_headers = await _signup(client, "uploaded@example.com")
    uploaded_cid = await _company(client, uploaded_headers)
    await _upload(client, uploaded_headers, uploaded_cid, TWO_MONTHS)

    manual_headers = await _signup(client, "typed@example.com")
    manual_cid = await _company(client, manual_headers)
    categories = (
        await client.get(
            f"/api/v1/categories?company_id={manual_cid}", headers=manual_headers
        )
    ).json()
    by_name = {c["name"]: c["id"] for c in categories}
    entries = [
        ("2026-06-05", "200000", "Client invoice", "Revenue"),
        ("2026-06-07", "90000", "Salaries for June", "Payroll"),
        ("2026-06-10", "30000", "Office rent", "Rent"),
        ("2026-07-05", "300000", "Client invoice", "Revenue"),
        ("2026-07-07", "150000", "Salaries for July", "Payroll"),
        ("2026-07-10", "30000", "Office rent", "Rent"),
        ("2026-07-20", "20000", "Google Ads campaign", "Marketing"),
    ]
    resp = await client.post(
        "/api/v1/transactions",
        headers=manual_headers,
        json={
            "company_id": manual_cid,
            "transactions": [
                {
                    "date": date,
                    "amount": amount,
                    "description": description,
                    "category_id": by_name[category],
                }
                for date, amount, description, category in entries
            ],
        },
    )
    assert resp.status_code == 201, resp.text

    uploaded = await _report(client, uploaded_headers, uploaded_cid, "2026-07")
    typed = await _report(client, manual_headers, manual_cid, "2026-07")

    for field in ("total_revenue", "total_expenses", "net_cash_flow", "burn_rate",
                  "gross_margin_pct", "revenue_growth_pct"):
        assert uploaded["kpis"][field] == typed["kpis"][field], field
    assert uploaded["closing_cash"] == typed["closing_cash"]
    assert [(c["name"], c["total"]) for c in uploaded["categories"]] == [
        (c["name"], c["total"]) for c in typed["categories"]
    ]
