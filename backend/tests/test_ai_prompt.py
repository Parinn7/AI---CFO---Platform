"""The AI CFO's system prompt (task 7.3, FR-6.3 / FR-6.5).

A prompt is configuration written in prose, which makes it easy to change by
accident and impossible to typecheck. These tests pin the parts that are
promises rather than wording: that the rules are stated before the numbers they
govern, that a company with no data gets an explicit "you have nothing to answer
from" instead of a silently empty block, that the standing constraints (never
calculate, plain language, not a licensed professional) are actually present,
and that assembling the prompt never smuggles a transaction into the payload —
the §4.1 guarantee 7.2 makes about the *context*, checked here against the whole
request.

They deliberately assert on short, load-bearing phrases rather than whole
paragraphs: the prompt should stay free to be reworded, but not free to quietly
lose a rule.
"""

import datetime as dt
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.ai_cfo.context import from_snapshot
from app.ai_cfo.models import ROLE_ASSISTANT, ROLE_USER, ChatMessage
from app.ai_cfo.prompt import (
    ASSISTANT,
    MAX_HISTORY_MESSAGES,
    NO_FIGURES_BLOCK,
    SYSTEM,
    SYSTEM_PROMPT,
    USER,
    build_messages,
    system_message,
)
from app.ai_cfo.service import (
    PLACEHOLDER_REPLY,
    build_prompt,
    get_session_for_user,
    replayable_history,
)
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
async def env() -> AsyncGenerator[tuple[AsyncClient, async_sessionmaker], None]:
    """Client plus the session factory behind it.

    The prompt is assembled inside the service and never returned by the
    message endpoint, so some of these tests have to call `build_prompt`
    directly against the same database the requests wrote to.
    """
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
        yield ac, session_factory
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


async def _session(client: AsyncClient, headers: dict, cid: str) -> str:
    return (
        await client.post(
            "/api/v1/chat/sessions", headers=headers, json={"company_id": cid}
        )
    ).json()["id"]


async def _ask(client: AsyncClient, headers: dict, sid: str, text: str) -> dict:
    resp = await client.post(
        f"/api/v1/chat/sessions/{sid}/messages", headers=headers, json={"content": text}
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# Same shape as the 7.2 fixture: every KPI defined at once, and one transaction
# carrying a string that must never appear in anything the model is sent.
BURNING_CSV = (
    b"date,amount,description,type\n"
    b"2024-06-10,500000,FY24 subscriptions,income\n"
    b"2025-03-10,400000,FY25 subscriptions,income\n"
    b"2025-09-15,600000,Enterprise deal,income\n"
    b"2026-01-20,300000,SaaS revenue,income\n"
    b"2026-01-25,1350000,Payroll,expense\n"
    b"2026-02-14,250000,ACME-VENDOR-SECRET invoice,expense\n"
)


def _context():
    """A rendered context, built without a database."""
    snapshot = KpiSnapshot(
        id=uuid.uuid4(),
        company_id=uuid.uuid4(),
        period_start=dt.date(2025, 3, 1),
        period_end=dt.date(2026, 2, 28),
        total_revenue=Decimal("900000.00"),
        total_expenses=Decimal("1150000.00"),
        net_cash_flow=Decimal("-250000.00"),
        burn_rate=Decimal("20833.33"),
        runway_months=Decimal("17.29"),
        gross_margin_pct=Decimal("-27.78"),
        operating_margin_pct=Decimal("-27.78"),
        revenue_growth_pct=Decimal("70.05"),
        created_at=dt.datetime(2026, 3, 1, 12, 0),
    )
    company = Company(
        id=snapshot.company_id,
        owner_user_id=uuid.uuid4(),
        name="Northwind Analytics",
        industry="SaaS",
        currency="INR",
        fiscal_year_start_month=4,
    )
    return from_snapshot(company, snapshot)


# --- The standing rules are actually in the prompt ---


def test_the_prompt_forbids_the_model_doing_arithmetic():
    """§4.1 / FR-6.6 as an instruction. This is the rule the whole platform
    rests on — a model that quietly works out "so about ₹50L a year" produces
    something indistinguishable from a real figure at a glance."""
    assert "Do no arithmetic" in SYSTEM_PROMPT
    assert "percentages" in SYSTEM_PROMPT
    # And the escape hatch is closed: not "unless it's simple".
    assert "trivial" in SYSTEM_PROMPT
    assert "not in the block, it does not exist" in SYSTEM_PROMPT


def test_the_prompt_requires_plain_non_technical_language():
    """FR-6.3. The reader runs a company; they are not an accountant."""
    assert "not an accountant" in SYSTEM_PROMPT
    assert "Plain, ordinary English" in SYSTEM_PROMPT
    assert "explain it in the same breath" in SYSTEM_PROMPT


def test_the_prompt_carries_the_advisory_disclaimer_rule():
    """FR-6.5. The permanent notice on `/chat` is the guarantee; this is the
    instruction to say it *in* an answer that gives advice, where someone is
    actually reading, rather than as boilerplate nobody sees."""
    assert "not a licensed financial professional" in SYSTEM_PROMPT
    assert "shades into a recommendation" in SYSTEM_PROMPT
    assert "read nowhere" in SYSTEM_PROMPT


def test_the_prompt_rules_out_invented_figures_and_benchmarks():
    """The context has no industry comparison data in it, so any benchmark the
    model offered would be recalled from training, not from this company."""
    assert "Never invent" in SYSTEM_PROMPT
    assert "benchmark" in SYSTEM_PROMPT


def test_the_prompt_says_not_applicable_is_not_zero():
    """The 7.2 context marks undefined figures explicitly; this stops them being
    read as zero on the way out."""
    assert '"Not applicable" is undefined, not zero' in SYSTEM_PROMPT


# --- Assembly ---


def test_system_message_states_the_rules_before_the_figures():
    """Order is deliberate: the constraints govern the numbers, and the stable
    half goes first so a provider can cache the prefix."""
    message = system_message(_context())
    assert message.startswith(SYSTEM_PROMPT)
    assert "FIGURES (already calculated" in message
    assert message.index(SYSTEM_PROMPT) < message.index("FIGURES (already calculated")
    assert "Northwind Analytics" in message


def test_a_company_with_no_data_gets_an_explicit_empty_block():
    """Not an absent block — an absent one reads as "no constraints" and invites
    the model to answer from general knowledge, which is exactly the generic
    advice FR-6.2 exists to rule out."""
    message = system_message(None)
    assert NO_FIGURES_BLOCK in message
    assert "FIGURES (already calculated" not in message
    assert "add their data first" in message
    assert "do not invent example" in message


def test_the_question_is_the_last_message_and_the_rules_the_first():
    messages = build_messages(_context(), [], "How long will my cash last?")
    assert messages[0].role == SYSTEM
    assert messages[-1].role == USER
    assert messages[-1].content == "How long will my cash last?"
    assert len(messages) == 2


def test_history_is_carried_in_order_between_the_rules_and_the_question():
    history = [(USER, "What's my burn?"), (ASSISTANT, "About that much.")]
    messages = build_messages(_context(), history, "And my runway?")
    assert [m.role for m in messages] == [SYSTEM, USER, ASSISTANT, USER]
    assert messages[1].content == "What's my burn?"
    assert messages[-1].content == "And my runway?"


def test_history_is_capped_so_the_figures_stay_salient():
    """A long conversation must not push the figure block out of the model's
    attention — the block is the only thing it may quote from."""
    history = [
        (USER if i % 2 == 0 else ASSISTANT, f"turn {i}") for i in range(40)
    ]
    messages = build_messages(_context(), history, "next?")
    carried = messages[1:-1]
    assert len(carried) == MAX_HISTORY_MESSAGES
    # The *most recent* turns survive, not the oldest.
    assert carried[-1].content == "turn 39"


def test_the_history_window_never_opens_on_an_assistant_turn():
    """Trimming can land mid-exchange. An assistant message with nothing before
    it reads as the model having spoken first — some providers reject it
    outright, the rest interpret it oddly."""
    history = [(ASSISTANT, "dangling")] + [
        (USER if i % 2 == 0 else ASSISTANT, f"turn {i}") for i in range(4)
    ]
    messages = build_messages(_context(), history, "next?")
    assert messages[1].role == USER
    assert "dangling" not in [m.content for m in messages]


def test_only_the_three_standard_roles_are_emitted():
    """7.4 maps these onto whichever provider is chosen; anything else would
    have to be special-cased there."""
    history = [(USER, "a"), (ASSISTANT, "b")]
    messages = build_messages(None, history, "c")
    assert {m.role for m in messages} <= {SYSTEM, USER, ASSISTANT}


# --- History filtering ---


def test_placeholder_turns_are_dropped_from_replayed_history():
    """Every conversation started before 7.4 holds assistant turns saying the
    assistant isn't connected. Replaying those shows the model a transcript in
    which it already refused to help."""
    messages = [
        ChatMessage(session_id=uuid.uuid4(), role=ROLE_USER, content="Hi"),
        ChatMessage(
            session_id=uuid.uuid4(), role=ROLE_ASSISTANT, content=PLACEHOLDER_REPLY
        ),
        ChatMessage(session_id=uuid.uuid4(), role=ROLE_USER, content="Still there?"),
    ]
    assert replayable_history(messages) == [(ROLE_USER, "Hi"), (ROLE_USER, "Still there?")]


def test_real_answers_are_replayed_even_when_their_figures_are_stale():
    """Only the inert placeholder is dropped. Editing a real answer out of the
    transcript would be rewriting what the user was told; the system prompt
    instead says that only the current block is authoritative."""
    messages = [
        ChatMessage(session_id=uuid.uuid4(), role=ROLE_USER, content="Burn?"),
        ChatMessage(
            session_id=uuid.uuid4(),
            role=ROLE_ASSISTANT,
            content="Your burn rate was ₹20,833.33 per month.",
        ),
    ]
    assert replayable_history(messages) == [
        (ROLE_USER, "Burn?"),
        (ROLE_ASSISTANT, "Your burn rate was ₹20,833.33 per month."),
    ]


# --- End to end, against real conversations ---


async def test_the_assembled_prompt_never_contains_a_transaction(env):
    """The §4.1 guarantee, checked against the whole payload rather than the
    context block alone — assembly is the last place a transaction could slip
    in, and this is what actually gets sent."""
    client, session_factory = env
    headers = await _signup(client, "prompt-boundary@example.com")
    cid = await _company(client, headers, name="Northwind Analytics", industry="SaaS")
    await _upload(client, headers, cid, BURNING_CSV)
    sid = await _session(client, headers, cid)
    await _ask(client, headers, sid, "Why are my expenses so high?")

    async with session_factory() as db:
        session = await get_session_for_user(
            db, uuid.UUID(sid), (await db.get(Company, uuid.UUID(cid))).owner_user_id
        )
        messages, context = await build_prompt(db, session, "And my runway?")

    assert context is not None
    whole = "\n".join(m.content for m in messages)
    assert "ACME-VENDOR-SECRET" not in whole
    assert "Payroll" not in whole
    assert "Enterprise deal" not in whole
    # The figures themselves are there — this isn't passing by being empty.
    assert "Northwind Analytics" in whole
    assert "Burn rate" in whole


async def test_a_conversations_placeholder_answers_do_not_reach_the_prompt(env):
    """The service-level half of the filtering test above, on real stored rows."""
    client, session_factory = env
    headers = await _signup(client, "prompt-history@example.com")
    cid = await _company(client, headers)
    await _upload(client, headers, cid, BURNING_CSV)
    sid = await _session(client, headers, cid)
    await _ask(client, headers, sid, "First question")
    await _ask(client, headers, sid, "Second question")

    async with session_factory() as db:
        session = await get_session_for_user(
            db, uuid.UUID(sid), (await db.get(Company, uuid.UUID(cid))).owner_user_id
        )
        messages, _ = await build_prompt(db, session, "Third question")

    assert [m.role for m in messages] == [SYSTEM, USER, USER, USER]
    assert [m.content for m in messages[1:]] == [
        "First question",
        "Second question",
        "Third question",
    ]
    assert PLACEHOLDER_REPLY not in "\n".join(m.content for m in messages)


# --- The endpoint ---


async def test_prompt_endpoint_returns_the_rules_and_this_company_figures(env):
    client, _ = env
    headers = await _signup(client, "prompt-endpoint@example.com")
    cid = await _company(client, headers, name="Northwind Analytics", industry="SaaS")
    await _upload(client, headers, cid, BURNING_CSV)

    body = (
        await client.get(f"/api/v1/chat/prompt?company_id={cid}", headers=headers)
    ).json()

    assert body["system_prompt"] == SYSTEM_PROMPT
    assert body["system_message"].startswith(SYSTEM_PROMPT)
    assert "Northwind Analytics" in body["system_message"]
    assert "Burn rate" in body["system_message"]
    assert body["max_history_messages"] == MAX_HISTORY_MESSAGES


async def test_prompt_endpoint_is_answerable_before_any_data_exists(env):
    """Having entered nothing is a normal state, and the instructions exist
    regardless — so this is a 200 describing an empty block, not a 404."""
    client, _ = env
    headers = await _signup(client, "prompt-nodata@example.com")
    cid = await _company(client, headers)

    resp = await client.get(f"/api/v1/chat/prompt?company_id={cid}", headers=headers)
    assert resp.status_code == 200
    assert NO_FIGURES_BLOCK in resp.json()["system_message"]


async def test_prompt_endpoint_requires_auth_and_ownership(env):
    client, _ = env
    mine = await _signup(client, "prompt-owner@example.com")
    cid = await _company(client, mine)

    assert (await client.get(f"/api/v1/chat/prompt?company_id={cid}")).status_code == 401

    theirs = await _signup(client, "prompt-other@example.com")
    resp = await client.get(f"/api/v1/chat/prompt?company_id={cid}", headers=theirs)
    assert resp.status_code == 404
