"""Endpoint tests for the Investor Readiness Summary (task 8.3, FR-7.3):
GET /reports/investor.

Where 8.1's tests pin "this month, correctly" and 8.2's pin the trailing-period
comparison, these pin what the investor summary adds: that the window is a
trailing *year* of available data against the year before it, that the run-rate
is the latest month annualised rather than the year averaged, that burn
efficiency is stated only where it means something, and that the readiness
checks are the fixed rules of `financial_engine/readiness.py` applied to real
engine figures.
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
        files={"file": ("data.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201, resp.text


def _rows(months, revenue, payroll, rent=20000) -> list[bytes]:
    return [
        line
        for month in months
        for line in (
            f"{month}-05,{revenue},Client invoice,income\n".encode(),
            f"{month}-07,{payroll},Salaries,expense\n".encode(),
            f"{month}-10,{rent},Office rent,expense\n".encode(),
        )
    ]


def _two_years() -> bytes:
    """Jan 2025 – Dec 2026, a company that doubled and stayed profitable.

    2025: revenue 100k/mo, payroll 60k + rent 20k → net +20k/mo.
          Year: revenue 12,00,000 · expenses 9,60,000 · net 2,40,000.
    2026: revenue 200k/mo, payroll 150k + rent 20k → net +30k/mo.
          Year: revenue 24,00,000 · expenses 20,40,000 · net 3,60,000.

    So: 100% growth, 15% operating margin, cash never negative — the company an
    investor summary should read as ready on every check.
    """
    header = [b"date,amount,description,type\n"]
    y1 = _rows([f"2025-{m:02d}" for m in range(1, 13)], 100000, 60000)
    y2 = _rows([f"2026-{m:02d}" for m in range(1, 13)], 200000, 150000)
    return b"".join(header + y1 + y2)


def _burning() -> bytes:
    """Jul 2025 – Jun 2026: growing revenue, but spending far ahead of it.

    2nd half 2025: revenue 50k/mo, payroll 300k + rent 20k → −270k/mo.
    1st half 2026: revenue 100k/mo, payroll 400k + rent 20k → −320k/mo.

    Cash goes deeply negative, revenue grows — a company burning to buy growth,
    which is what the burn multiple exists to read.
    """
    header = [b"date,amount,description,type\n"]
    h1 = _rows([f"2025-{m:02d}" for m in range(7, 13)], 50000, 300000)
    h2 = _rows([f"2026-{m:02d}" for m in range(1, 7)], 100000, 400000)
    return b"".join(header + h1 + h2)


async def _summary(
    client: AsyncClient, headers: dict, cid: str, end_month=None
) -> dict:
    query = f"?company_id={cid}"
    if end_month:
        query += f"&end_month={end_month}"
    resp = await client.get(f"/api/v1/reports/investor{query}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _checks(body: dict) -> dict:
    return {check["key"]: check for check in body["checks"]}


# --- The window ---


async def test_window_is_the_trailing_year_against_the_year_before_it(
    client: AsyncClient,
):
    """An investor's unit of assessment is the year, anchored on the latest
    month of available data like every other window in this system."""
    headers = await _signup(client, "window@example.com")
    cid = await _company(client, headers, "Northwind")
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert body["report_type"] == "investor"
    assert body["company"]["name"] == "Northwind"
    assert body["num_months"] == 12
    assert body["window"]["period_start"] == "2026-01-01"
    assert body["window"]["period_end"] == "2026-12-31"
    assert body["previous"]["period_start"] == "2025-01-01"
    assert body["previous"]["period_end"] == "2025-12-31"

    assert body["window"]["kpis"]["total_revenue"] == "2400000.00"
    assert body["previous"]["kpis"]["total_revenue"] == "1200000.00"
    assert body["movement"]["revenue_change"] == "1200000.00"


async def test_both_years_quote_stored_snapshots_not_second_calculations(
    client: AsyncClient,
):
    """architecture §4.1: a report assembles. Each year's `kpis` is a real
    `kpi_snapshots` row, and regenerating must not mint duplicates."""
    headers = await _signup(client, "snapshots@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)
    await _summary(client, headers, cid)  # again — must reuse, not re-mint

    stored = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    by_id = {s["id"]: s for s in stored}

    for side, start in (("window", "2026-01-01"), ("previous", "2025-01-01")):
        snapshot_id = body[side]["kpis"]["id"]
        assert snapshot_id in by_id, f"{side} kpis are not a stored snapshot"
        assert by_id[snapshot_id]["period_start"] == start
        rows = [s for s in stored if s["period_start"] == start]
        assert len(rows) == 1, f"{side} minted more than one snapshot"


async def test_explicit_end_month_anchors_a_different_year(client: AsyncClient):
    headers = await _signup(client, "anchor@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid, end_month="2025-12")

    assert body["window"]["period_start"] == "2025-01-01"
    assert body["window"]["kpis"]["total_revenue"] == "1200000.00"
    # Nothing precedes 2025, so the prior year is honest zeros — and says so.
    assert body["previous"]["has_data"] is False
    assert body["previous"]["kpis"]["total_revenue"] == "0.00"


# --- The metrics investors evaluate ---


async def test_run_rate_is_the_latest_month_annualised(client: AsyncClient):
    """Not the year averaged: 2025's quieter months would understate what the
    business is earning now. The year's total travels alongside it."""
    headers = await _signup(client, "runrate@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert body["run_rate"]["month"] == "2026-12"
    assert body["run_rate"]["monthly"] == "200000.00"
    assert body["run_rate"]["annualised"] == "2400000.00"


async def test_cash_position_reconciles_with_the_year(client: AsyncClient):
    """`closing − opening` is the year's net cash flow by construction."""
    headers = await _signup(client, "cash@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert body["cash"]["opening_cash"] == "240000.00"  # all of 2025's surplus
    assert body["cash"]["closing_cash"] == "600000.00"
    assert body["cash"]["net_change"] == body["window"]["kpis"]["net_cash_flow"]


async def test_burn_multiple_is_absent_for_a_profitable_company(
    client: AsyncClient,
):
    """A profitable year has no burn to divide — 0 would read as perfect
    capital efficiency, which is a different claim."""
    headers = await _signup(client, "nomultiple@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    assert (await _summary(client, headers, cid))["burn_multiple"] is None


async def test_burn_multiple_reads_cash_burned_per_rupee_of_new_revenue(
    client: AsyncClient,
):
    headers = await _signup(client, "multiple@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _burning())

    body = await _summary(client, headers, cid)

    # Window (Jul 2025–Jun 2026): revenue 9L, expenses 45.6L → burn 36.6L.
    # Prior year holds only Jul–Dec 2025 was excluded, so new revenue is
    # measured against the preceding twelve months' 3L.
    assert body["window"]["kpis"]["total_revenue"] == "900000.00"
    assert body["previous"]["kpis"]["total_revenue"] == "0.00"
    # No prior revenue at all → no "new revenue" denominator that means
    # anything, so the whole window's revenue counts as new.
    burned = -float(body["window"]["kpis"]["net_cash_flow"])
    assert float(body["burn_multiple"]) == round(burned / 900000, 2)


async def test_history_is_measured_over_the_company_not_the_window(
    client: AsyncClient,
):
    """Track record is how long the company has been measurable at all — the
    window is a reporting choice, not a fact about the business."""
    headers = await _signup(client, "history@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert body["months_of_history"] == 24
    assert body["months_with_revenue"] == 24


# --- The readiness checklist ---


async def test_every_check_is_graded_and_carries_the_rule_it_applied(
    client: AsyncClient,
):
    """The screen states the threshold rather than keeping its own copy, so the
    printed rule is always the rule that was applied."""
    headers = await _signup(client, "checks@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)
    checks = _checks(body)

    assert set(checks) == {
        "track_record",
        "runway",
        "revenue_growth",
        "operating_margin",
        "revenue_consistency",
        "categorized_spend",
    }
    for check in body["checks"]:
        assert check["status"] in {"ready", "attention", "gap", "not_applicable"}
        assert check["unit"] in {"months", "pct"}
        assert check["ready_at"] is not None
        assert check["detail"]

    assert checks["track_record"]["value"] == "24"
    assert checks["revenue_growth"]["value"] == "100.00"
    assert checks["operating_margin"]["value"] == "15.00"
    assert checks["revenue_consistency"]["value"] == "100.00"
    assert checks["categorized_spend"]["value"] == "100.00"


async def test_a_strong_company_reads_ready_throughout(client: AsyncClient):
    headers = await _signup(client, "ready@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert {c["status"] for c in body["checks"]} == {"ready"}
    assert body["overall_status"] == "ready"


async def test_a_company_burning_past_its_cash_reads_as_a_gap(
    client: AsyncClient,
):
    """Growth doesn't offset a runway that doesn't exist — the overall status is
    the weakest link, not an average."""
    headers = await _signup(client, "gap@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _burning())

    body = await _summary(client, headers, cid)
    checks = _checks(body)

    assert body["overall_status"] == "gap"
    # Burning with a negative recorded cash balance: the engine leaves runway
    # undefined, and that is the worst finding on the list, not an absent one.
    assert checks["runway"]["status"] == "gap"
    assert checks["runway"]["value"] is None
    assert checks["operating_margin"]["status"] == "gap"
    assert checks["track_record"]["status"] == "ready"  # 12 months on record


async def test_uncategorized_spend_is_graded_by_value_not_count(
    client: AsyncClient,
):
    """Uncategorized spend is a diligence finding: expenses a reader can't be
    told the purpose of. One large unexplained payment outweighs many small
    explained ones."""
    headers = await _signup(client, "uncategorized@example.com")
    cid = await _company(client, headers)
    csv = b"".join(
        [b"date,amount,description,type\n"]
        + _rows([f"2026-{m:02d}" for m in range(1, 13)], 200000, 150000)
        # A big expense the rules can't place, in one month only.
        + [b"2026-06-15,900000,zzz,expense\n"]
    )
    await _upload(client, headers, cid, csv)

    body = await _summary(client, headers, cid)
    lines = {line["name"]: line for line in body["categories"]}

    assert "Uncategorized" in lines, "uncategorized spend must be reported, not dropped"
    check = _checks(body)["categorized_spend"]
    assert check["status"] in {"attention", "gap"}
    assert float(check["value"]) < 95


async def test_a_short_track_record_is_stated_not_hidden(client: AsyncClient):
    """Four months of data is a real finding about readiness, and the empty
    months before the company existed must not read as inconsistent revenue."""
    headers = await _signup(client, "young@example.com")
    cid = await _company(client, headers)
    csv = b"".join(
        [b"date,amount,description,type\n"]
        + _rows([f"2026-{m:02d}" for m in range(1, 5)], 200000, 100000)
    )
    await _upload(client, headers, cid, csv)

    body = await _summary(client, headers, cid)
    checks = _checks(body)

    assert body["months_of_history"] == 4
    assert checks["track_record"]["status"] == "gap"
    assert checks["revenue_consistency"]["status"] == "ready"
    assert checks["revenue_consistency"]["value"] == "100.00"


async def test_no_prior_year_is_not_applicable_never_a_quiet_pass(
    client: AsyncClient,
):
    """Growth against a year with no records isn't measurable. Reporting it as
    a pass — or as +100% against zero — would be a claim the data can't make."""
    headers = await _signup(client, "noprior@example.com")
    cid = await _company(client, headers)
    csv = b"".join(
        [b"date,amount,description,type\n"]
        + _rows([f"2026-{m:02d}" for m in range(1, 13)], 200000, 150000)
    )
    await _upload(client, headers, cid, csv)

    body = await _summary(client, headers, cid)
    growth = _checks(body)["revenue_growth"]

    assert body["previous"]["has_data"] is False
    assert growth["status"] == "not_applicable"
    assert growth["value"] is None


# --- Shape, boundaries, and the two input paths ---


async def test_monthly_series_is_the_window_month_by_month(client: AsyncClient):
    headers = await _signup(client, "shape@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)

    assert [m["month"] for m in body["monthly"]] == [
        f"2026-{m:02d}" for m in range(1, 13)
    ]
    assert all(m["revenue"] == "200000.00" for m in body["monthly"])


async def test_cost_structure_adds_up_to_the_window_expenses(client: AsyncClient):
    headers = await _signup(client, "costs@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    body = await _summary(client, headers, cid)
    expenses = [line for line in body["categories"] if line["type"] == "expense"]

    assert sum(float(line["total"]) for line in expenses) == float(
        body["window"]["kpis"]["total_expenses"]
    )


async def test_company_with_no_data_at_all_is_404(client: AsyncClient):
    headers = await _signup(client, "nodata@example.com")
    cid = await _company(client, headers)

    resp = await client.get(
        f"/api/v1/reports/investor?company_id={cid}", headers=headers
    )
    assert resp.status_code == 404
    assert "No financial data" in resp.json()["detail"]


async def test_bad_end_month_is_rejected(client: AsyncClient):
    headers = await _signup(client, "badinput@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _two_years())

    for bad in ("2026-13", "December", "26-12", "2026-1"):
        resp = await client.get(
            f"/api/v1/reports/investor?company_id={cid}&end_month={bad}",
            headers=headers,
        )
        assert resp.status_code == 400, bad


async def test_summary_requires_auth_and_ownership(client: AsyncClient):
    owner = await _signup(client, "investorowner@example.com")
    cid = await _company(client, owner)
    await _upload(client, owner, cid, _two_years())

    anon = await client.get(f"/api/v1/reports/investor?company_id={cid}")
    assert anon.status_code == 401

    intruder = await _signup(client, "investorintruder@example.com")
    resp = await client.get(
        f"/api/v1/reports/investor?company_id={cid}", headers=intruder
    )
    # 404, not 403 — the endpoint doesn't confirm the company exists.
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Company not found."


async def test_manual_entries_produce_an_identical_summary(client: AsyncClient):
    """FR-2.6 through the investor summary (groundwork for task 8.5): typed
    figures must grade exactly as uploaded ones do."""
    uploaded = await _signup(client, "investoruploaded@example.com")
    uploaded_cid = await _company(client, uploaded)
    await _upload(client, uploaded, uploaded_cid, _two_years())

    typed = await _signup(client, "investortyped@example.com")
    typed_cid = await _company(client, typed)
    categories = (
        await client.get(
            f"/api/v1/categories?company_id={typed_cid}", headers=typed
        )
    ).json()
    by_name = {c["name"]: c["id"] for c in categories}
    entries = []
    for year, revenue, payroll in (("2025", "100000", "60000"), ("2026", "200000", "150000")):
        for month in range(1, 13):
            entries += [
                {
                    "date": f"{year}-{month:02d}-05",
                    "amount": revenue,
                    "description": "Client invoice",
                    "category_id": by_name["Revenue"],
                },
                {
                    "date": f"{year}-{month:02d}-07",
                    "amount": payroll,
                    "description": "Salaries",
                    "category_id": by_name["Payroll"],
                },
                {
                    "date": f"{year}-{month:02d}-10",
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

    from_upload = await _summary(client, uploaded, uploaded_cid)
    from_typing = await _summary(client, typed, typed_cid)

    assert from_upload["run_rate"] == from_typing["run_rate"]
    assert from_upload["cash"] == from_typing["cash"]
    assert from_upload["movement"] == from_typing["movement"]
    assert from_upload["burn_multiple"] == from_typing["burn_multiple"]
    assert from_upload["overall_status"] == from_typing["overall_status"]
    assert from_upload["months_of_history"] == from_typing["months_of_history"]
    assert [
        (c["key"], c["status"], c["value"], c["detail"]) for c in from_upload["checks"]
    ] == [
        (c["key"], c["status"], c["value"], c["detail"]) for c in from_typing["checks"]
    ]
