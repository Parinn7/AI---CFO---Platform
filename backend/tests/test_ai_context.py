"""Context assembly for the AI CFO (task 7.2, FR-6.2 / architecture §4.1).

These pin the boundary the whole feature rests on: the assistant is handed
**precomputed KPI figures and nothing else**. So the tests check three things —
that the context is built from the right `kpi_snapshots` row, that every number
in it is that row's stored value rather than something re-derived, and that no
transaction of any kind reaches it.

The reply itself is still the 7.1 placeholder (the provider lands in 7.4), which
is what makes 7.2 testable on its own: the observable result of assembling
context is which snapshot ends up on the assistant turn.
"""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai_cfo.context import NOT_APPLICABLE, build_figures, from_snapshot, render
from app.ai_cfo.service import context_period
from app.companies.models import Company
from app.core.database import Base, get_db
from app.financial_engine.models import KpiSnapshot
from app.main import app
from app.transactions.categories import DEFAULT_CATEGORIES
from app.transactions.models import Category

from app.auth import models as _auth_models  # noqa: F401
from app.companies import models as _company_models  # noqa: F401
from app.financial_engine import models as _fin_models  # noqa: F401
from app.scenarios import models as _scenario_models  # noqa: F401
from app.ai_cfo import models as _ai_cfo_models  # noqa: F401


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


async def _company(client: AsyncClient, headers: dict, **fields) -> str:
    body = {"name": "Acme", **fields}
    return (
        await client.post("/api/v1/companies", headers=headers, json=body)
    ).json()["id"]


async def _upload(client: AsyncClient, headers: dict, cid: str, csv: bytes) -> None:
    resp = await client.post(
        "/api/v1/uploads",
        headers=headers,
        data={"company_id": cid},
        files={"file": ("t.csv", csv, "text/csv")},
    )
    assert resp.status_code == 201, resp.text


async def _ask(client: AsyncClient, headers: dict, cid: str, text: str) -> dict:
    sid = (
        await client.post(
            "/api/v1/chat/sessions", headers=headers, json={"company_id": cid}
        )
    ).json()["id"]
    resp = await client.post(
        f"/api/v1/chat/sessions/{sid}/messages", headers=headers, json={"content": text}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _context(client: AsyncClient, headers: dict, cid: str) -> dict:
    resp = await client.get(f"/api/v1/chat/context?company_id={cid}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


# A burning, growing company, deliberately shaped so *every* KPI is defined at
# once: revenue before the window (so growth has a baseline), more revenue
# inside it, expenses that exceed that revenue (so it's burning), but a positive
# cumulative cash position (so runway is a real number rather than "out of
# cash"). The last transaction is Feb 2026, which anchors the 12-month window.
BURNING_CSV = (
    b"date,amount,description,type\n"
    b"2024-06-10,500000,FY24 subscriptions,income\n"
    b"2025-03-10,400000,FY25 subscriptions,income\n"
    b"2025-09-15,600000,Enterprise deal,income\n"
    b"2026-01-20,300000,SaaS revenue,income\n"
    b"2026-01-25,1350000,Payroll,expense\n"
    b"2026-02-14,250000,ACME-VENDOR-SECRET invoice,expense\n"
)


def _snapshot(**overrides) -> KpiSnapshot:
    """A detached snapshot row, for the pure rendering tests."""
    fields = {
        "id": uuid.uuid4(),
        "company_id": uuid.uuid4(),
        "period_start": dt.date(2025, 3, 1),
        "period_end": dt.date(2026, 2, 28),
        "total_revenue": Decimal("900000.00"),
        "total_expenses": Decimal("1150000.00"),
        "net_cash_flow": Decimal("-250000.00"),
        "burn_rate": Decimal("20833.33"),
        "runway_months": Decimal("17.29"),
        "gross_margin_pct": Decimal("-27.78"),
        "operating_margin_pct": Decimal("-27.78"),
        "revenue_growth_pct": Decimal("70.05"),
        "created_at": dt.datetime(2026, 3, 1, 12, 0),
    }
    fields.update(overrides)
    return KpiSnapshot(**fields)


def _figure(snapshot: KpiSnapshot, key: str):
    return next(f for f in build_figures(snapshot) if f.key == key)


# --- The boundary: only precomputed figures reach the assistant ---


async def test_context_quotes_the_snapshot_and_no_transactions(client: AsyncClient):
    """The whole point of FR-6.2 / §4.1: the assistant sees stored KPI values,
    never the rows they were computed from. A transaction with a distinctive
    description must not appear anywhere in what the model is handed."""
    headers = await _signup(client, "boundary@example.com")
    cid = await _company(client, headers, industry="SaaS")
    await _upload(client, headers, cid, BURNING_CSV)

    body = await _context(client, headers, cid)
    assert body["available"] is True
    ctx = body["context"]

    # Not the descriptions, not the individual amounts, not the dates.
    assert "ACME-VENDOR-SECRET" not in ctx["rendered"]
    assert "Payroll" not in ctx["rendered"]
    assert "2026-02-14" not in ctx["rendered"]
    assert "250000" not in ctx["rendered"].replace(",", "")

    # And the figures that *are* there are the snapshot's own, unaltered.
    snaps = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    stored = next(s for s in snaps if s["id"] == ctx["snapshot_id"])
    values = {f["key"]: f["value"] for f in ctx["figures"]}
    assert Decimal(stored["total_revenue"]) == Decimal("1300000.00")
    assert values["total_revenue"] == "₹13,00,000.00 (₹13L)"
    assert values["total_expenses"] == "₹16,00,000.00 (₹16L)"
    # Nothing is undefined for this company, so nothing is hand-waved.
    assert values["runway_months"] == "8.0 months"
    assert values["revenue_growth_pct"] == "+160.0%"
    assert NOT_APPLICABLE not in values.values()


async def test_context_covers_the_last_twelve_months_of_data(client: AsyncClient):
    """The same window the dashboard and a scenario baseline use — anchored on
    the latest transaction, not on today. An answer quoting a different period
    from the one on screen would be indefensible even if both were right."""
    headers = await _signup(client, "window@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, BURNING_CSV)

    ctx = (await _context(client, headers, cid))["context"]
    assert ctx["period_start"] == "2025-03-01"
    assert ctx["period_end"] == "2026-02-28"
    assert ctx["num_months"] == 12


async def test_answers_are_tagged_with_the_snapshot_they_were_given(
    client: AsyncClient,
):
    """`kpi_context_snapshot_id` is the audit trail for §4.1 — it must name the
    row the context was built from."""
    headers = await _signup(client, "tagged@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, BURNING_CSV)

    turn = await _ask(client, headers, cid, "How long will my cash last?")
    assert turn["user_message"]["kpi_context_snapshot_id"] is None
    attached = turn["assistant_message"]["kpi_context_snapshot_id"]
    assert attached is not None
    assert attached == (await _context(client, headers, cid))["context"]["snapshot_id"]


async def test_a_company_with_no_data_gets_no_context(client: AsyncClient):
    """Nothing computed means nothing to ground an answer in. Fabricating a
    snapshot of zeros would hand the model figures that read as findings
    ("your revenue is ₹0") rather than an absence of data."""
    headers = await _signup(client, "nodata@example.com")
    cid = await _company(client, headers)

    body = await _context(client, headers, cid)
    assert body["available"] is False
    assert body["context"] is None
    assert "no transactions" in body["unavailable_reason"].lower()

    turn = await _ask(client, headers, cid, "How am I doing?")
    assert turn["assistant_message"]["kpi_context_snapshot_id"] is None


# --- Snapshot selection: reused while current, refreshed when stale ---


async def test_a_conversation_reuses_one_snapshot(client: AsyncClient):
    """Asking repeatedly must not write a `kpi_snapshots` row per question —
    the figures haven't changed, so neither should the snapshot."""
    headers = await _signup(client, "reuse@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, BURNING_CSV)

    ids = {
        (await _ask(client, headers, cid, q))["assistant_message"][
            "kpi_context_snapshot_id"
        ]
        for q in ("What's my burn rate?", "And my runway?", "Is that bad?")
    }
    assert len(ids) == 1

    snaps = (
        await client.get(
            f"/api/v1/financial/kpi-snapshots?company_id={cid}", headers=headers
        )
    ).json()
    assert len(snaps) == 1


async def test_new_data_moves_later_answers_onto_fresh_figures(client: AsyncClient):
    """A stale snapshot would make the audit trail point at figures the answer
    never used, so recording transactions mid-conversation must produce a new
    one for subsequent turns."""
    headers = await _signup(client, "stale@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, BURNING_CSV)

    before = (await _ask(client, headers, cid, "How am I doing?"))[
        "assistant_message"
    ]["kpi_context_snapshot_id"]

    # More revenue inside the same window — the KPIs genuinely change.
    await _upload(
        client,
        headers,
        cid,
        b"date,amount,description,type\n2026-02-20,500000,Big deal,income\n",
    )
    after = (await _ask(client, headers, cid, "And now?"))["assistant_message"][
        "kpi_context_snapshot_id"
    ]
    assert after != before


# --- Rendering: undefined figures are stated, not dropped ---


def test_runway_distinguishes_not_burning_from_out_of_cash():
    """Both store null, and confusing them is the worst mistake this block could
    make — one is good news, the other is an emergency."""
    profitable = _figure(
        _snapshot(runway_months=None, burn_rate=Decimal("-5000.00")), "runway_months"
    )
    assert profitable.value == NOT_APPLICABLE
    assert "nothing to run out of" in profitable.note

    broke = _figure(
        _snapshot(runway_months=None, burn_rate=Decimal("20000.00")), "runway_months"
    )
    assert broke.value == NOT_APPLICABLE
    assert "no positive cash balance" in broke.note
    assert "serious" in broke.note


def test_a_defined_runway_is_placed_against_the_urgency_threshold():
    """The note has to say where *this* runway sits, not just quote the
    threshold. The model is handed this text verbatim, and "under six months is
    urgent" printed beside a 17-month runway reads as a warning about a company
    that isn't in trouble."""
    healthy = _figure(
        _snapshot(runway_months=Decimal("17.29"), burn_rate=Decimal("421573.50")),
        "runway_months",
    )
    assert healthy.note == "Above the six months usually treated as urgent."

    urgent = _figure(
        _snapshot(runway_months=Decimal("2.50"), burn_rate=Decimal("421573.50")),
        "runway_months",
    )
    assert urgent.note == "Below the six months usually treated as urgent."


def test_undefined_margin_and_growth_say_why():
    """A dropped null would read as zero or as unknown; both mislead."""
    figures = build_figures(
        _snapshot(gross_margin_pct=None, revenue_growth_pct=None, total_revenue=Decimal("0.00"))
    )
    by_key = {f.key: f for f in figures}
    assert by_key["gross_margin_pct"].value == NOT_APPLICABLE
    assert "no revenue" in by_key["gross_margin_pct"].note
    assert by_key["revenue_growth_pct"].value == NOT_APPLICABLE
    assert "preceding period" in by_key["revenue_growth_pct"].note


def test_a_surplus_is_stated_as_a_surplus():
    """Stored burn is negative when the company is cash-generative. "Negative
    burn" is technically right and useless to read."""
    figure = _figure(_snapshot(burn_rate=Decimal("-42000.00")), "burn_rate")
    assert "surplus" in figure.value
    assert "-" not in figure.value
    assert "cash-generative" in figure.note


def test_rendered_block_marks_the_figures_as_already_calculated():
    """The block has to say so itself — 7.3's prompt leans on it, and a reader
    checking §4.1 should see the instruction where the numbers are."""
    company = Company(
        id=uuid.uuid4(), name="Northwind Analytics", industry="SaaS", currency="INR"
    )
    snapshot = _snapshot(company_id=company.id)
    text = render(from_snapshot(company, snapshot))

    assert "Northwind Analytics" in text
    assert "SaaS" in text
    assert "never recalculate" in text
    assert str(snapshot.id) in text
    assert "1 Mar 2025 to 28 Feb 2026 (12 months)" in text
    # Figures read the way the dashboard writes them.
    assert "₹9,00,000.00 (₹9L)" in text
    assert "17.3 months" in text
    assert "+70.1%" in text


def test_context_period_is_whole_calendar_months():
    start, end = context_period((2026, 2))
    assert (start, end) == (dt.date(2025, 3, 1), dt.date(2026, 2, 28))
    # Leap year, and a December anchor rolling the year over.
    assert context_period((2024, 2))[1] == dt.date(2024, 2, 29)
    assert context_period((2026, 12)) == (dt.date(2026, 1, 1), dt.date(2026, 12, 31))


# --- Scoping ---


async def test_context_requires_auth_and_ownership(client: AsyncClient):
    cid = await _company(client, await _signup(client, "owner@example.com"))
    assert (await client.get(f"/api/v1/chat/context?company_id={cid}")).status_code == 401

    intruder = await _signup(client, "intruder@example.com")
    resp = await client.get(f"/api/v1/chat/context?company_id={cid}", headers=intruder)
    assert resp.status_code == 404
