"""Endpoint tests for the Board Report (task 8.2, FR-7.2): GET /reports/board.

Where the monthly report's tests pin "this month, correctly", these pin the
things a board report adds: that the window is a *trailing* quarter/year of
available data, that both periods are stated off real `kpi_snapshots` rows
rather than one snapshot and one hand-rolled total, that cash reconciles
(`closing − opening` is the period's net cash flow), and that the flagged spend
and saved plans travel as read, never re-derived.
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
from app.scenarios import models as _scenario_models  # noqa: F401


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
    assert resp.status_code == 201, resp.text


def _six_months() -> bytes:
    """Feb–Jul 2026. The first quarter (Feb–Apr) is steady; the second
    (May–Jul) grows revenue and payroll — a trajectory a board would ask about.

    Quarter 1: revenue 100k/mo, payroll 60k/mo, rent 20k/mo → net +20k/mo.
    Quarter 2: revenue 200k/mo, payroll 150k/mo, rent 20k/mo → net +30k/mo.
    """
    rows = [b"date,amount,description,type\n"]
    for month, revenue, payroll in (
        ("02", 100000, 60000),
        ("03", 100000, 60000),
        ("04", 100000, 60000),
        ("05", 200000, 150000),
        ("06", 200000, 150000),
        ("07", 200000, 150000),
    ):
        rows.append(f"2026-{month}-05,{revenue},Client invoice,income\n".encode())
        rows.append(f"2026-{month}-07,{payroll},Salaries,expense\n".encode())
        rows.append(f"2026-{month}-10,20000,Office rent,expense\n".encode())
    return b"".join(rows)


async def _board(
    client: AsyncClient, headers: dict, cid: str, period=None, end_month=None
) -> dict:
    query = f"?company_id={cid}"
    if period:
        query += f"&period={period}"
    if end_month:
        query += f"&end_month={end_month}"
    resp = await client.get(f"/api/v1/reports/board{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_default_period_is_the_trailing_quarter_of_available_data(
    client: AsyncClient,
):
    """"Last quarter" means of available data — books kept in arrears would
    otherwise report a quarter two-thirds empty, which reads as a collapse."""
    headers = await _signup(client, "quarter@example.com")
    cid = await _company(client, headers, "Northwind")
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid)

    assert body["report_type"] == "board"
    assert body["company"]["name"] == "Northwind"
    assert body["period"] == "quarter"
    assert body["num_months"] == 3
    assert body["current"]["period_start"] == "2026-05-01"
    assert body["current"]["period_end"] == "2026-07-31"
    assert body["current"]["start_month"] == "2026-05"
    assert body["current"]["end_month"] == "2026-07"

    kpis = body["current"]["kpis"]
    assert kpis["total_revenue"] == "600000.00"  # 3 × 200k
    assert kpis["total_expenses"] == "510000.00"  # 3 × 170k
    assert kpis["net_cash_flow"] == "90000.00"


async def test_previous_period_is_the_preceding_calendar_quarter(client: AsyncClient):
    """Both sides of the comparison are real snapshots for whole months — a
    board compares Q3 with Q2, not with a window three days longer."""
    headers = await _signup(client, "previous@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid)
    previous = body["previous"]

    assert previous["period_start"] == "2026-02-01"
    assert previous["period_end"] == "2026-04-30"
    assert previous["has_data"] is True
    assert previous["kpis"]["total_revenue"] == "300000.00"  # 3 × 100k
    assert previous["kpis"]["total_expenses"] == "240000.00"  # 3 × 80k

    movement = body["movement"]
    assert movement["revenue_change"] == "300000.00"
    assert movement["expenses_change"] == "270000.00"
    assert movement["net_change"] == "30000.00"  # 90k − 60k
    # Both quarters run a surplus, so both burn rates are negative; the burn
    # deepened by 10k/mo — stated as the change between two engine figures.
    assert movement["burn_rate_change"] == "-10000.00"


async def test_both_periods_quote_stored_snapshots_not_second_calculations(
    client: AsyncClient,
):
    """architecture §4.1: a report assembles. Each period's `kpis` must be a
    real `kpi_snapshots` row, and regenerating must not mint duplicates."""
    headers = await _signup(client, "snapshots@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid)
    await _board(client, headers, cid)  # again — must reuse, not re-mint

    stored = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    by_id = {s["id"]: s for s in stored}

    for side, start in (("current", "2026-05-01"), ("previous", "2026-02-01")):
        snapshot_id = body[side]["kpis"]["id"]
        assert snapshot_id in by_id, f"{side} kpis are not a stored snapshot"
        assert by_id[snapshot_id]["period_start"] == start
        rows = [s for s in stored if s["period_start"] == start]
        assert len(rows) == 1, f"{side} period minted more than one snapshot"


async def test_cash_position_reconciles_with_the_period_result(client: AsyncClient):
    """`closing − opening` is the period's net cash flow by construction. The
    board report states both so a reader can see the runway's numerator and the
    quarter's result reconcile."""
    headers = await _signup(client, "cash@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid)
    cash = body["cash"]

    # Feb–Apr banked 3 × 20k before the quarter opened.
    assert cash["opening_cash"] == "60000.00"
    assert cash["closing_cash"] == "150000.00"
    assert cash["net_change"] == "90000.00"
    assert cash["net_change"] == body["current"]["kpis"]["net_cash_flow"]


async def test_year_period_covers_twelve_months(client: AsyncClient):
    headers = await _signup(client, "year@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid, period="year")

    assert body["num_months"] == 12
    assert body["current"]["period_start"] == "2025-08-01"
    assert body["current"]["period_end"] == "2026-07-31"
    # Only six months have data, so the year's totals are the six months'.
    assert body["current"]["kpis"]["total_revenue"] == "900000.00"
    # The preceding year has nothing recorded — honest zeros, flagged as such.
    assert body["previous"]["period_start"] == "2024-08-01"
    assert body["previous"]["has_data"] is False
    assert body["previous"]["kpis"]["total_revenue"] == "0.00"
    assert body["previous"]["transaction_count"] == 0


async def test_explicit_end_month_produces_a_calendar_quarter(client: AsyncClient):
    """Naming the last month is how a calendar or fiscal quarter is asked for."""
    headers = await _signup(client, "endmonth@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid, end_month="2026-04")

    assert body["current"]["period_start"] == "2026-02-01"
    assert body["current"]["period_end"] == "2026-04-30"
    assert body["current"]["kpis"]["total_revenue"] == "300000.00"
    assert body["previous"]["period_start"] == "2025-11-01"
    assert body["previous"]["has_data"] is False


async def test_monthly_shape_is_the_period_month_by_month(client: AsyncClient):
    """A quarter's three months, zero-filled where empty (FR-4.6) — the shape
    of the period, not just its total."""
    headers = await _signup(client, "monthly@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    monthly = (await _board(client, headers, cid))["monthly"]

    assert [m["month"] for m in monthly] == ["2026-05", "2026-06", "2026-07"]
    assert monthly[0]["revenue"] == "200000.00"
    assert monthly[0]["expenses"] == "170000.00"
    assert monthly[-1]["net_cash_flow"] == "30000.00"

    # A year's series is twelve continuous months, empty ones included.
    yearly = (await _board(client, headers, cid, period="year"))["monthly"]
    assert len(yearly) == 12
    assert yearly[0] == {
        "month": "2025-08",
        "revenue": "0.00",
        "expenses": "0.00",
        "net_cash_flow": "0.00",
        "margin_pct": None,
    }


async def test_cost_structure_adds_up_to_the_period_expenses(client: AsyncClient):
    headers = await _signup(client, "costs@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    body = await _board(client, headers, cid)
    lines = body["categories"]

    assert [line["name"] for line in lines] == ["Revenue", "Payroll", "Rent"]
    expenses = [line for line in lines if line["type"] == "expense"]
    assert sum(float(line["total"]) for line in expenses) == float(
        body["current"]["kpis"]["total_expenses"]
    )
    payroll = next(line for line in lines if line["name"] == "Payroll")
    assert payroll["total"] == "450000.00"  # 3 × 150k
    assert payroll["transaction_count"] == 3


async def test_watch_items_group_flagged_spend_by_category_and_month(
    client: AsyncClient,
):
    """A board reads exposure, not card charges (FR-3.6): one line per category
    per month, largest first."""
    headers = await _signup(client, "watch@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2026-01-10,20000,Google Ads,expense\n"
        b"2026-02-10,20000,Google Ads,expense\n"
        b"2026-03-10,20000,Google Ads,expense\n"
        b"2026-04-08,150000,Conference campaign,expense\n"
        b"2026-04-20,50000,Google Ads blowout,expense\n",
    )
    flagged = (
        await client.post(
            "/api/v1/transactions/detect-anomalies",
            headers=headers,
            json={"company_id": cid},
        )
    ).json()["flagged"]
    assert flagged == 2  # both April marketing rows are in the flagged bucket

    body = await _board(client, headers, cid, end_month="2026-04")
    items = body["watch_items"]

    assert len(items) == 1, "one category in one month is one line"
    assert items[0] == {
        "month": "2026-04",
        "category_name": "Marketing",
        "total": "200000.00",
        "transaction_count": 2,
    }

    # A period with nothing flagged says so rather than listing the company's
    # whole history of flags.
    assert (await _board(client, headers, cid, end_month="2026-03"))[
        "watch_items"
    ] == []


async def test_saved_scenarios_travel_as_stored(client: AsyncClient):
    """The plans on the table (FR-5.4), read verbatim out of `scenarios.result`
    — a board paper says what the plan looked like when it was modelled."""
    headers = await _signup(client, "plans@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    saved = await client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={
            "company_id": cid,
            "name": "Hire two engineers",
            "period_start": "2026-05-01",
            "period_end": "2026-07-31",
            "assumptions": {"new_hires": 2, "avg_salary_per_hire": "100000"},
        },
    )
    assert saved.status_code == 201, saved.text
    stored = saved.json()

    summary = (await _board(client, headers, cid))["scenarios"]
    assert len(summary) == 1
    assert summary[0]["id"] == stored["id"]
    assert summary[0]["name"] == "Hire two engineers"
    assert summary[0]["period_start"] == "2026-05-01"
    assert summary[0]["expenses_change"] == stored["result"]["deltas"][
        "total_expenses"
    ]
    assert summary[0]["net_cash_flow_change"] == stored["result"]["deltas"][
        "net_cash_flow"
    ]
    assert (
        summary[0]["scenario_runway_months"]
        == stored["result"]["scenario"]["runway_months"]
    )


async def test_scenarios_are_capped_at_the_newest_few(client: AsyncClient):
    """A board pack carries the plans still being argued about, not an archive."""
    headers = await _signup(client, "manyplans@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    for n in range(1, 6):
        resp = await client.post(
            "/api/v1/scenarios",
            headers=headers,
            json={
                "company_id": cid,
                "name": f"Plan {n}",
                "period_start": "2026-05-01",
                "period_end": "2026-07-31",
                "assumptions": {"revenue_change_pct": str(n * 5)},
            },
        )
        assert resp.status_code == 201, resp.text

    scenarios = (await _board(client, headers, cid))["scenarios"]
    assert len(scenarios) == 3
    assert {s["name"] for s in scenarios} <= {f"Plan {n}" for n in range(1, 6)}


async def test_company_with_no_data_at_all_is_404(client: AsyncClient):
    headers = await _signup(client, "nodata@example.com")
    cid = await _company(client, headers)

    resp = await client.get(f"/api/v1/reports/board?company_id={cid}", headers=headers)
    assert resp.status_code == 404
    assert "No financial data" in resp.json()["detail"]


async def test_bad_period_and_bad_end_month_are_rejected(client: AsyncClient):
    headers = await _signup(client, "badinput@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _six_months())

    resp = await client.get(
        f"/api/v1/reports/board?company_id={cid}&period=decade", headers=headers
    )
    assert resp.status_code == 422

    for bad in ("2026-13", "July", "26-07", "2026-7"):
        resp = await client.get(
            f"/api/v1/reports/board?company_id={cid}&end_month={bad}", headers=headers
        )
        assert resp.status_code == 400, bad


async def test_board_report_requires_auth_and_ownership(client: AsyncClient):
    owner = await _signup(client, "boardowner@example.com")
    cid = await _company(client, owner)
    await _upload(client, owner, cid, _six_months())

    anon = await client.get(f"/api/v1/reports/board?company_id={cid}")
    assert anon.status_code == 401

    intruder = await _signup(client, "boardintruder@example.com")
    resp = await client.get(
        f"/api/v1/reports/board?company_id={cid}", headers=intruder
    )
    # 404, not 403 — the endpoint doesn't confirm the company exists.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Company not found."


async def test_manual_entries_produce_an_identical_board_report(client: AsyncClient):
    """FR-2.6 through the board report (groundwork for task 8.5): the same
    figures typed by hand must produce the same pack."""
    uploaded = await _signup(client, "boarduploaded@example.com")
    uploaded_cid = await _company(client, uploaded)
    await _upload(client, uploaded, uploaded_cid, _six_months())

    typed = await _signup(client, "boardtyped@example.com")
    typed_cid = await _company(client, typed)
    categories = (
        await client.get(
            f"/api/v1/categories?company_id={typed_cid}", headers=typed
        )
    ).json()
    by_name = {c["name"]: c["id"] for c in categories}
    entries = []
    for month, revenue, payroll in (
        ("02", "100000", "60000"),
        ("03", "100000", "60000"),
        ("04", "100000", "60000"),
        ("05", "200000", "150000"),
        ("06", "200000", "150000"),
        ("07", "200000", "150000"),
    ):
        entries += [
            {
                "date": f"2026-{month}-05",
                "amount": revenue,
                "description": "Client invoice",
                "category_id": by_name["Revenue"],
            },
            {
                "date": f"2026-{month}-07",
                "amount": payroll,
                "description": "Salaries",
                "category_id": by_name["Payroll"],
            },
            {
                "date": f"2026-{month}-10",
                "amount": "20000",
                "description": "Office rent",
                "category_id": by_name["Rent"],
            },
        ]
    resp = await client.post(
        "/api/v1/transactions",
        headers=typed,
        json={"company_id": typed_cid, "transactions": entries},
    )
    assert resp.status_code == 201, resp.text

    from_upload = await _board(client, uploaded, uploaded_cid)
    from_typing = await _board(client, typed, typed_cid)

    for side in ("current", "previous"):
        for field in (
            "total_revenue",
            "total_expenses",
            "net_cash_flow",
            "burn_rate",
            "gross_margin_pct",
            "revenue_growth_pct",
        ):
            assert (
                from_upload[side]["kpis"][field] == from_typing[side]["kpis"][field]
            ), f"{side}.{field}"
    assert from_upload["cash"] == from_typing["cash"]
    assert from_upload["movement"] == from_typing["movement"]
    assert [(c["name"], c["total"]) for c in from_upload["categories"]] == [
        (c["name"], c["total"]) for c in from_typing["categories"]
    ]
