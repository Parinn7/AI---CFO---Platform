"""Endpoint tests for the scenario simulator (task 6.2, FR-5.2/FR-5.3):
POST /scenarios/simulate."""

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


# One clean month: revenue 100k, expenses 60k (of which 20k is Marketing).
# Auto-categorization runs inline on upload, so "Marketing spend" lands in the
# Marketing category (task 4.1).
_JAN = (
    b"date,amount,description,type\n"
    b"2026-01-10,100000,Jan sales,income\n"
    b"2026-01-15,40000,Salaries,expense\n"
    b"2026-01-20,20000,Marketing spend,expense\n"
)


async def _simulate(client: AsyncClient, headers: dict, cid: str, **levers) -> dict:
    resp = await client.post(
        "/api/v1/scenarios/simulate",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "assumptions": levers,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_baseline_matches_the_kpi_snapshot_for_the_same_period(
    client: AsyncClient,
):
    """The simulator reuses the Financial Engine, so its `baseline` block must
    equal what POST /financial/kpi-snapshots stores for the same window."""
    headers = await _signup(client, "base@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    snapshot = (
        await client.post(
            "/api/v1/financial/kpi-snapshots",
            headers=headers,
            json={
                "company_id": cid,
                "period_start": "2026-01-01",
                "period_end": "2026-01-31",
            },
        )
    ).json()
    baseline = (await _simulate(client, headers, cid))["baseline"]

    for field in (
        "total_revenue",
        "total_expenses",
        "net_cash_flow",
        "burn_rate",
        "runway_months",
        "gross_margin_pct",
        "operating_margin_pct",
        "revenue_growth_pct",
    ):
        assert baseline[field] == snapshot[field], field


async def test_no_op_scenario_returns_identical_sides(client: AsyncClient):
    headers = await _signup(client, "noop@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    body = await _simulate(client, headers, cid)
    assert body["baseline"] == body["scenario"]
    assert body["deltas"]["total_revenue"] == "0.00"
    assert body["deltas"]["net_cash_flow"] == "0.00"


async def test_hiring_turns_a_profit_into_a_burn(client: AsyncClient):
    """Baseline: +40k net. Hiring 2 people at 30k/month for the 1-month period
    adds 60k of expenses → net -20k, i.e. the company starts burning."""
    headers = await _signup(client, "hire@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    body = await _simulate(
        client, headers, cid, new_hires=2, avg_salary_per_hire="30000"
    )
    assert body["applied"]["added_payroll"] == "60000.00"
    assert body["baseline"]["net_cash_flow"] == "40000.00"
    assert body["scenario"]["total_expenses"] == "120000.00"
    assert body["scenario"]["net_cash_flow"] == "-20000.00"
    assert body["deltas"]["net_cash_flow"] == "-60000.00"
    # Burn flips from -40k (a surplus) to +20k (burning).
    assert body["baseline"]["burn_rate"] == "-40000.00"
    assert body["scenario"]["burn_rate"] == "20000.00"
    # Baseline is profitable → no runway. The scenario burns 20k/month against
    # the company's *real* 40k of cash → 2 months of runway (the cash position
    # is not restated; decided with the user in 6.2).
    assert body["baseline"]["runway_months"] is None
    assert body["scenario"]["runway_months"] == "2.00"
    # Undefined on one side only → the difference isn't a number.
    assert body["deltas"]["runway_months"] is None


async def test_marketing_lever_uses_the_categorised_marketing_total(
    client: AsyncClient,
):
    """+50% applies to the 20k booked to Marketing, not to all 60k of expenses."""
    headers = await _signup(client, "mktg@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    body = await _simulate(client, headers, cid, marketing_change_pct="50")
    assert body["applied"]["marketing_baseline"] == "20000.00"
    assert body["applied"]["marketing_change"] == "10000.00"
    assert body["scenario"]["total_expenses"] == "70000.00"


async def test_pricing_and_revenue_compose_multiplicatively(client: AsyncClient):
    headers = await _signup(client, "price@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    body = await _simulate(
        client, headers, cid, pricing_change_pct="10", revenue_change_pct="20"
    )
    assert body["applied"]["revenue_multiplier"] == "1.3200"
    assert body["scenario"]["total_revenue"] == "132000.00"
    assert body["deltas"]["total_revenue"] == "32000.00"


async def test_scenario_can_create_a_runway(client: AsyncClient):
    """A profitable company has no runway; cutting revenue makes it burn, and
    runway is that burn against the cash it actually has."""
    headers = await _signup(client, "runway@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    body = await _simulate(client, headers, cid, revenue_change_pct="-50")
    # Revenue 50k vs 60k expenses → burning 10k/month.
    assert body["scenario"]["total_revenue"] == "50000.00"
    assert body["scenario"]["burn_rate"] == "10000.00"
    # Real cash on hand is 40k → 4 months. Cash is *not* restated under the
    # scenario, so this answers "how long does my actual money last?".
    assert body["scenario"]["runway_months"] == "4.00"
    assert body["baseline"]["runway_months"] is None


async def test_growth_compares_against_the_real_prior_window(client: AsyncClient):
    """A scenario doesn't rewrite history: growth is measured against what the
    preceding window actually did."""
    headers = await _signup(client, "growth@example.com")
    cid = await _company(client, headers)
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n"
        b"2025-12-10,80000,Dec sales,income\n"
        b"2026-01-10,100000,Jan sales,income\n"
        b"2026-01-20,20000,Marketing spend,expense\n",
    )
    body = await _simulate(client, headers, cid, pricing_change_pct="10")
    # Baseline: (100k − 80k)/80k = +25%. Scenario: (110k − 80k)/80k = +37.5%.
    assert body["baseline"]["revenue_growth_pct"] == "25.00"
    assert body["scenario"]["revenue_growth_pct"] == "37.50"
    assert body["deltas"]["revenue_growth_pct"] == "12.50"


async def test_simulate_persists_nothing(client: AsyncClient):
    """Stateless by design (architecture §5.2) — simulating must not create a
    KPI snapshot or alter the transactions."""
    headers = await _signup(client, "stateless@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    before = (
        await client.get(
            f"/api/v1/transactions?company_id={cid}", headers=headers
        )
    ).json()
    await _simulate(client, headers, cid, new_hires=3, avg_salary_per_hire="50000")

    snapshots = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    assert snapshots == []
    after = (
        await client.get(
            f"/api/v1/transactions?company_id={cid}", headers=headers
        )
    ).json()
    assert after == before


async def test_out_of_range_lever_is_rejected(client: AsyncClient):
    headers = await _signup(client, "range@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    resp = await client.post(
        "/api/v1/scenarios/simulate",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "assumptions": {"marketing_change_pct": "5000"},
        },
    )
    assert resp.status_code == 422


async def test_reversed_period_is_rejected(client: AsyncClient):
    headers = await _signup(client, "period@example.com")
    cid = await _company(client, headers)

    resp = await client.post(
        "/api/v1/scenarios/simulate",
        headers=headers,
        json={
            "company_id": cid,
            "period_start": "2026-01-31",
            "period_end": "2026-01-01",
            "assumptions": {},
        },
    )
    assert resp.status_code == 422


async def test_requires_auth(client: AsyncClient):
    resp = await client.post(
        "/api/v1/scenarios/simulate",
        json={
            "company_id": "00000000-0000-0000-0000-000000000000",
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "assumptions": {},
        },
    )
    assert resp.status_code == 401


async def test_other_users_company_is_404(client: AsyncClient):
    owner = await _signup(client, "owner@example.com")
    cid = await _company(client, owner)
    intruder = await _signup(client, "intruder@example.com")

    resp = await client.post(
        "/api/v1/scenarios/simulate",
        headers=intruder,
        json={
            "company_id": cid,
            "period_start": "2026-01-01",
            "period_end": "2026-01-31",
            "assumptions": {},
        },
    )
    assert resp.status_code == 404


async def test_company_with_no_data_simulates_to_zeros(client: AsyncClient):
    headers = await _signup(client, "empty@example.com")
    cid = await _company(client, headers)

    body = await _simulate(client, headers, cid, pricing_change_pct="50")
    assert body["baseline"]["total_revenue"] == "0.00"
    assert body["scenario"]["total_revenue"] == "0.00"  # 50% of nothing
    assert body["baseline"]["gross_margin_pct"] is None
    assert body["deltas"]["gross_margin_pct"] is None


async def test_cash_on_hand_is_not_restated_by_the_scenario(client: AsyncClient):
    """The scenario changes the burn rate, never the money in the bank — so two
    scenarios that burn the same amount have the same runway regardless of how
    they got there (decided with the user in 6.2)."""
    headers = await _signup(client, "cash@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    # Both land on 80k of expenses vs 100k revenue... but via different levers:
    # +20k of hiring, vs +100% of the 20k marketing budget.
    by_hiring = await _simulate(
        client, headers, cid, new_hires=1, avg_salary_per_hire="20000"
    )
    by_marketing = await _simulate(client, headers, cid, marketing_change_pct="100")

    assert by_hiring["scenario"]["total_expenses"] == "80000.00"
    assert by_marketing["scenario"]["total_expenses"] == "80000.00"
    assert (
        by_hiring["scenario"]["runway_months"]
        == by_marketing["scenario"]["runway_months"]
    )
    # Still profitable (100k revenue vs 80k expenses) → no runway either way.
    assert by_hiring["scenario"]["runway_months"] is None
