"""Endpoint tests for saving and revisiting scenarios (task 6.4, FR-5.4):
POST /scenarios, GET /scenarios, GET/DELETE /scenarios/{id}.

The behaviour worth pinning here isn't the arithmetic (6.2's tests cover that)
but the *storage contract*: a saved scenario replays the answer it gave when it
was saved, is scoped to its owner, and can only ever hold engine-computed
figures.
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
        await client.post("/api/v1/companies", headers=headers, json={"name": name})
    ).json()["id"]


async def _upload(client: AsyncClient, headers: dict, cid: str, csv: bytes) -> None:
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201, resp.text


# Same one-month fixture the 6.2 tests use: revenue 100k, expenses 60k
# (20k of it Marketing, categorised inline on upload).
_JAN = (
    b"date,amount,description,type\n"
    b"2026-01-10,100000,Jan sales,income\n"
    b"2026-01-15,40000,Salaries,expense\n"
    b"2026-01-20,20000,Marketing spend,expense\n"
)

_FEB = b"date,amount,description,type\n2026-01-25,500000,Big new contract,income\n"

_PERIOD = {"period_start": "2026-01-01", "period_end": "2026-01-31"}

_LEVERS = {
    "new_hires": 2,
    "avg_salary_per_hire": "30000",
    "marketing_change_pct": "50",
    "pricing_change_pct": "0",
    "revenue_change_pct": "0",
}


async def _save(
    client: AsyncClient, headers: dict, cid: str, name: str = "Hire two", **over
) -> dict:
    body = {"company_id": cid, "name": name, **_PERIOD, "assumptions": _LEVERS}
    body.update(over)
    resp = await client.post("/api/v1/scenarios", headers=headers, json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_saved_result_equals_a_fresh_simulation(client: AsyncClient):
    """Saving re-runs the same engine, so the stored `result` must be exactly
    the document `/simulate` returns for the same inputs."""
    headers = await _signup(client, "save@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    simulated = (
        await client.post(
            "/api/v1/scenarios/simulate",
            headers=headers,
            json={"company_id": cid, **_PERIOD, "assumptions": _LEVERS},
        )
    ).json()
    saved = await _save(client, headers, cid)

    assert saved["result"] == simulated


async def test_saved_scenario_is_replayed_not_recomputed(client: AsyncClient):
    """The whole point of storing `result`: adding transactions afterwards must
    not silently restate a scenario the user already saved and read."""
    headers = await _signup(client, "replay@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    saved = await _save(client, headers, cid)
    at_save_time = saved["result"]

    # The company's real numbers move on.
    await _upload(client, headers, cid, _FEB)

    revisited = (
        await client.get(f"/api/v1/scenarios/{saved['id']}", headers=headers)
    ).json()
    assert revisited["result"] == at_save_time

    # ...and a fresh run against today's data genuinely differs, so the test
    # above is pinning replay rather than an accident of identical inputs.
    rerun = (
        await client.post(
            "/api/v1/scenarios/simulate",
            headers=headers,
            json={"company_id": cid, **_PERIOD, "assumptions": _LEVERS},
        )
    ).json()
    assert rerun["baseline"]["total_revenue"] != at_save_time["baseline"]["total_revenue"]


async def test_assumptions_round_trip_for_reloading_into_the_form(
    client: AsyncClient,
):
    """A saved scenario is only revisitable if its levers come back in the shape
    the input form uses (`frontend/lib/scenarios.ts`)."""
    headers = await _signup(client, "levers@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    saved = await _save(client, headers, cid)
    assert saved["assumptions"] == {
        "new_hires": 2,
        "avg_salary_per_hire": "30000",
        "marketing_change_pct": "50",
        "pricing_change_pct": "0",
        "revenue_change_pct": "0",
    }
    assert saved["result"]["assumptions"] == saved["assumptions"]


async def test_baseline_snapshot_matches_the_stored_comparison(client: AsyncClient):
    """`baseline_kpi_snapshot_id` must point at figures the saved comparison
    actually used — otherwise the traceability link is a lie."""
    headers = await _signup(client, "snap@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    saved = await _save(client, headers, cid)
    assert saved["baseline_kpi_snapshot_id"] is not None

    snapshots = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    snapshot = next(s for s in snapshots if s["id"] == saved["baseline_kpi_snapshot_id"])

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
        assert saved["result"]["baseline"][field] == snapshot[field], field


async def test_matching_snapshot_is_reused_and_a_stale_one_is_not(
    client: AsyncClient,
):
    """Two saves over unchanged data share one snapshot; once the data moves,
    the next save generates a fresh one rather than pointing at stale figures."""
    headers = await _signup(client, "reuse@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    first = await _save(client, headers, cid, name="One")
    second = await _save(client, headers, cid, name="Two")
    assert first["baseline_kpi_snapshot_id"] == second["baseline_kpi_snapshot_id"]

    await _upload(client, headers, cid, _FEB)
    third = await _save(client, headers, cid, name="Three")
    assert third["baseline_kpi_snapshot_id"] != first["baseline_kpi_snapshot_id"]


async def test_list_is_newest_first_and_scoped_to_the_company(client: AsyncClient):
    headers = await _signup(client, "list@example.com")
    cid = await _company(client, headers)
    other = await _company(client, headers, name="Other Co")
    await _upload(client, headers, cid, _JAN)
    await _upload(client, headers, other, _JAN)

    await _save(client, headers, cid, name="Older")
    await _save(client, headers, cid, name="Newer")
    await _save(client, headers, other, name="Someone else's plan")

    listed = (
        await client.get(f"/api/v1/scenarios?company_id={cid}", headers=headers)
    ).json()
    assert [s["name"] for s in listed] == ["Newer", "Older"]
    # Full comparison travels with the list, so revisiting needs no second call.
    assert listed[0]["result"]["num_months"] == 1


async def test_delete_removes_only_that_scenario(client: AsyncClient):
    headers = await _signup(client, "delete@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)
    keep = await _save(client, headers, cid, name="Keep")
    drop = await _save(client, headers, cid, name="Drop")

    assert (
        await client.delete(f"/api/v1/scenarios/{drop['id']}", headers=headers)
    ).status_code == 204
    assert (
        await client.get(f"/api/v1/scenarios/{drop['id']}", headers=headers)
    ).status_code == 404

    listed = (
        await client.get(f"/api/v1/scenarios?company_id={cid}", headers=headers)
    ).json()
    assert [s["name"] for s in listed] == ["Keep"]

    # The data the scenario was derived from is untouched.
    txns = (
        await client.get(f"/api/v1/transactions?company_id={cid}", headers=headers)
    ).json()
    assert len(txns) == 3


async def test_blank_name_is_rejected(client: AsyncClient):
    headers = await _signup(client, "blank@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    resp = await client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={"company_id": cid, "name": "   ", **_PERIOD, "assumptions": _LEVERS},
    )
    assert resp.status_code == 422


async def test_reversed_period_is_rejected(client: AsyncClient):
    headers = await _signup(client, "reversed@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)

    resp = await client.post(
        "/api/v1/scenarios",
        headers=headers,
        json={
            "company_id": cid,
            "name": "Backwards",
            "period_start": "2026-01-31",
            "period_end": "2026-01-01",
            "assumptions": _LEVERS,
        },
    )
    assert resp.status_code == 422


async def test_requires_auth(client: AsyncClient):
    headers = await _signup(client, "owner@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, _JAN)
    saved = await _save(client, headers, cid)

    assert (await client.get(f"/api/v1/scenarios?company_id={cid}")).status_code == 401
    assert (await client.get(f"/api/v1/scenarios/{saved['id']}")).status_code == 401
    assert (await client.delete(f"/api/v1/scenarios/{saved['id']}")).status_code == 401
    assert (
        await client.post(
            "/api/v1/scenarios",
            json={"company_id": cid, "name": "X", **_PERIOD, "assumptions": _LEVERS},
        )
    ).status_code == 401


async def test_another_users_scenario_is_404(client: AsyncClient):
    """404 rather than 403 — an outsider learns nothing about what exists."""
    owner = await _signup(client, "mine@example.com")
    cid = await _company(client, owner)
    await _upload(client, owner, cid, _JAN)
    saved = await _save(client, owner, cid)

    intruder = await _signup(client, "theirs@example.com")
    assert (
        await client.get(f"/api/v1/scenarios/{saved['id']}", headers=intruder)
    ).status_code == 404
    assert (
        await client.delete(f"/api/v1/scenarios/{saved['id']}", headers=intruder)
    ).status_code == 404
    assert (
        await client.get(f"/api/v1/scenarios?company_id={cid}", headers=intruder)
    ).status_code == 404
    assert (
        await client.post(
            "/api/v1/scenarios",
            headers=intruder,
            json={"company_id": cid, "name": "Nope", **_PERIOD, "assumptions": _LEVERS},
        )
    ).status_code == 404
