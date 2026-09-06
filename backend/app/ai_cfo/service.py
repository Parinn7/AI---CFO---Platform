"""AI CFO chat service (tasks 7.1–7.4) — sessions, history, context, answers.

The whole path behind a question. 7.1 built the interface and its persistence
(the chat screen, the two tables, owner-scoped access); 7.2 added the context
the model is given; 7.3 added the instructions it is given with it
(`prompt.py`); **7.4 added the provider that actually answers**
(`ai_cfo/providers`).

**Context assembly (7.2, FR-6.2 / architecture §4.1).** Before an answer is
produced, `build_context` resolves the company's current KPI snapshot and turns
it into the block in `ai_cfo/context.py`. The snapshot's id is stored on the
assistant turn, so every answer can be traced back to the exact figures behind
it. Raw transactions are never part of that context — see the context module.

**The provider is chosen by configuration, never by this module (7.4, FR-6.4).**
`answer_question` asks `providers.get_provider()` for whatever `LLM_PROVIDER`
names and hands it the assembled messages. Nothing here knows a vendor's name,
a model id or an HTTP endpoint, which is what makes the swap in FR-6.4 a config
change rather than an edit to the feature.

**The placeholder reply (decided in 7.1, still standing).** With no key
configured — a fresh clone, CI, or this project before the key existed — the
provider raises `LLMNotConfigured` and the fixed, clearly-labelled placeholder
is stored instead. It is deliberately inert: it states that the assistant isn't
connected, and it contains **no figures, no advice and no reference to the
company's data**. Storing a plausible-sounding stub answer would be far worse
than storing an obviously unfinished one — a demo could show it and a reader
could believe it. Real provider *failures* are not this case: they raise, so a
broken call is reported rather than recorded as something the assistant said.

**Placeholder turns are not replayed into the prompt.** Every conversation
started before a key was configured holds assistant turns saying the assistant
isn't connected. Feeding those back would teach the model that it had already
refused to help and invite it to keep doing so — so `replayable_history` drops
them. Dropping them is safe precisely because they are inert: nothing was said
that a later answer could need.
"""

from __future__ import annotations

import calendar
import datetime as dt
import logging
import uuid
from typing import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_cfo.context import CfoContext, from_snapshot
from app.ai_cfo.models import ROLE_ASSISTANT, ROLE_USER, ChatMessage, ChatSession
from app.ai_cfo.prompt import PromptMessage, build_messages
from app.ai_cfo.providers import LLMNotConfigured, LLMProvider, get_provider
from app.companies.models import Company
from app.financial_engine.calculations import month_range
from app.financial_engine.service import (
    latest_transaction_month,
    snapshot_for_period,
)

logger = logging.getLogger(__name__)

# The stub answer. No numbers, no advice — see the module docstring.
PLACEHOLDER_REPLY = (
    "The AI CFO isn't connected yet, so I can't answer that one properly.\n\n"
    "Everything around the answer is ready: your question was saved, this "
    "reply is tied to the exact set of precomputed figures the assistant will "
    "be handed, and the instructions it will follow are written. You can read "
    "both in the panel below. The one piece left is the connection to the "
    "language model itself.\n\n"
    "When it does answer, every figure it quotes will be one the Financial "
    "Engine calculated — it never works numbers out for itself. And it will "
    "never be a substitute for a licensed financial professional."
)


def _now() -> dt.datetime:
    """Timestamps are set here rather than left to the database's `now()`.

    Conversation order is a correctness property — a question must read back
    before its answer, and exchange 2 after exchange 1 — and leaving it to the
    server clock makes that guarantee depend on the backend's resolution.
    Postgres gives microseconds but stamps a whole transaction identically (so
    a question and its answer tie), and SQLite's CURRENT_TIMESTAMP only has
    **second** resolution (so an entire fast conversation ties). Python's clock
    is microsecond-resolution and behaves the same on both, which makes the
    ordering hold everywhere instead of only where the clock happens to be fine
    enough.
    """
    return dt.datetime.now(dt.timezone.utc)


async def create_session(
    db: AsyncSession, company_id: uuid.UUID, user_id: uuid.UUID
) -> ChatSession:
    """Start a conversation about a company (FR-6.1)."""
    session = ChatSession(company_id=company_id, user_id=user_id, created_at=_now())
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session_for_user(
    db: AsyncSession, session_id: uuid.UUID, user_id: uuid.UUID
) -> ChatSession | None:
    """A conversation, only if it belongs to a company the caller owns (NFR-3).

    Scoped by **company ownership**, not by `chat_sessions.user_id`: the
    company is what carries the financial data, and its owner is who may read
    discussions of it. `user_id` records who started the conversation, which is
    an authorship fact rather than the access rule.
    """
    result = await db.execute(
        select(ChatSession)
        .join(Company, ChatSession.company_id == Company.id)
        .where(ChatSession.id == session_id, Company.owner_user_id == user_id)
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession, company_id: uuid.UUID
) -> list[ChatSession]:
    """A company's conversations, newest first."""
    result = await db.execute(
        select(ChatSession)
        .where(ChatSession.company_id == company_id)
        .order_by(ChatSession.created_at.desc())
    )
    return list(result.scalars().all())


async def list_messages(
    db: AsyncSession, session_id: uuid.UUID
) -> list[ChatMessage]:
    """A conversation's turns, oldest first — reading order.

    `created_at` carries the order (see `_now`). The descending `role` tiebreak
    is a safety net for the one case where two turns could still share a
    timestamp — 'user' sorts after 'assistant', so descending puts the question
    first, which is the order they happened in.
    """
    result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at, ChatMessage.role.desc())
    )
    return list(result.scalars().all())


async def session_summaries(
    db: AsyncSession, session_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, str | None]]:
    """`{session_id: (message_count, first_user_question)}` for a set of
    sessions, in two queries rather than two per session — the session list
    needs both to be scannable."""
    if not session_ids:
        return {}

    counts = dict(
        (
            await db.execute(
                select(ChatMessage.session_id, func.count())
                .where(ChatMessage.session_id.in_(session_ids))
                .group_by(ChatMessage.session_id)
            )
        ).all()
    )

    # The opening question of each conversation, used as its label.
    rows = (
        await db.execute(
            select(ChatMessage.session_id, ChatMessage.content, ChatMessage.created_at)
            .where(
                ChatMessage.session_id.in_(session_ids),
                ChatMessage.role == ROLE_USER,
            )
            .order_by(ChatMessage.session_id, ChatMessage.created_at)
        )
    ).all()
    first: dict[uuid.UUID, str] = {}
    for sid, content, _ in rows:
        first.setdefault(sid, content)

    return {sid: (counts.get(sid, 0), first.get(sid)) for sid in session_ids}


# The context window: the last 12 months *of available data*, the same window
# the dashboard's history series and a scenario's baseline use. Answers that
# quoted a different period from the one on screen would be indefensible even
# when both were right.
CONTEXT_MONTHS = 12


def context_period(
    end_month: tuple[int, int], months: int = CONTEXT_MONTHS
) -> tuple[dt.date, dt.date]:
    """The `[start, end]` dates of the `months`-long window ending at
    `end_month`, aligned to whole calendar months."""
    window = month_range(end_month[0], end_month[1], months)
    start_year, start_mo = window[0]
    end_year, end_mo = end_month
    last_day = calendar.monthrange(end_year, end_mo)[1]
    return dt.date(start_year, start_mo, 1), dt.date(end_year, end_mo, last_day)


async def build_context(
    db: AsyncSession, company_id: uuid.UUID
) -> CfoContext | None:
    """Assemble what the AI CFO is given about a company (7.2, FR-6.2).

    Resolves the current KPI snapshot for the company's last 12 months of data
    and renders it via `ai_cfo.context`. Returns `None` when the company has no
    transactions at all — with nothing computed there is nothing to ground an
    answer in, and inventing a snapshot of zeros would hand the model a set of
    figures that look like findings ("your revenue is ₹0") rather than an
    absence of data.

    `snapshot_for_period` reuses the stored snapshot while it still states the
    current figures, so a long conversation doesn't write a new row per
    question, but recording transactions mid-conversation does move later
    answers onto fresh figures.
    """
    company = await db.get(Company, company_id)
    if company is None:
        return None

    end_month = await latest_transaction_month(db, company_id)
    if end_month is None:
        return None

    period_start, period_end = context_period(end_month)
    snapshot = await snapshot_for_period(db, company_id, period_start, period_end)
    return from_snapshot(company, snapshot)


def replayable_history(messages: Sequence[ChatMessage]) -> list[tuple[str, str]]:
    """A conversation's turns as `(role, content)`, minus the ones that would
    mislead the model if replayed.

    Only the placeholder is dropped, and only because it is inert: it says the
    assistant isn't connected and nothing else, so no later answer can depend on
    it, while replaying it would show the model a transcript in which it had
    already declined to help. Real answers are always replayed, including ones
    that quoted figures since superseded — the system prompt tells the model
    that only the current block is authoritative, which is the honest way to
    handle it. Silently editing history would not be.
    """
    return [
        (message.role, message.content)
        for message in messages
        if not (
            message.role == ROLE_ASSISTANT and message.content == PLACEHOLDER_REPLY
        )
    ]


async def build_prompt(
    db: AsyncSession, session: ChatSession, question: str
) -> tuple[tuple[PromptMessage, ...], CfoContext | None]:
    """The complete request for one question (7.3), and the context behind it.

    Returns both because the caller needs the context separately: its snapshot
    id is what gets written to `chat_messages.kpi_context_snapshot_id`, and
    digging it back out of the assembled text would be absurd.
    """
    context = await build_context(db, session.company_id)
    history = replayable_history(await list_messages(db, session.id))
    return build_messages(context, history, question), context


async def answer_question(
    db: AsyncSession,
    session: ChatSession,
    question: str,
    provider: LLMProvider | None = None,
) -> tuple[str, uuid.UUID | None]:
    """Produce the assistant's reply and the KPI snapshot it was grounded in.

    The whole path, as of 7.4: the context is assembled (7.2), the prompt is
    built around it (7.3), the configured provider is asked for an answer
    (7.4), and the snapshot id is returned so the turn records which figures
    that answer was built from.

    **With no provider connected, the placeholder still stands.** An empty
    `LLM_API_KEY` surfaces as `LLMNotConfigured`, which is caught here and
    answered with the inert 7.1 text — no figures, no advice, and an explicit
    statement that the assistant isn't wired up. That is the state a fresh
    clone and the test suite run in, and it stays a working screen rather than
    an error.

    **Every other provider failure propagates.** An outage, a rejected key or a
    blocked prompt raises out of here so that `post_message` never commits, and
    the router turns it into a 503. Writing "sorry, something went wrong" into
    `chat_messages` would put words in the assistant's mouth in a table that is
    meant to be an audit trail, and `replayable_history` would then feed that
    apology back into later prompts.

    `provider` is injectable for tests; production passes nothing and gets
    whatever `LLM_PROVIDER` names.

    `question` is passed through, never inspected. Branching on what was asked —
    picking a different period for a runway question, say — would be the
    assistant starting to reason about finances on its own, and the context is
    small enough that it can simply always carry everything.
    """
    messages, context = await build_prompt(db, session, question)
    snapshot_id = None if context is None else context.snapshot_id
    provider = provider or get_provider()

    try:
        completion = await provider.complete(messages)
    except LLMNotConfigured:
        logger.info(
            "No LLM provider connected; answering session %s with the placeholder.",
            session.id,
        )
        return PLACEHOLDER_REPLY, snapshot_id

    # Logged at INFO so a run can be audited for what answered and at what
    # cost. The prompt and the answer are not logged at any level: between them
    # they carry the company's figures and the founder's questions about them.
    usage = completion.usage
    logger.info(
        "AI CFO answered session %s via %s/%s (snapshot %s, finish %s, tokens %s/%s)",
        session.id,
        completion.provider,
        completion.model,
        snapshot_id,
        completion.finish_reason,
        None if usage is None else usage.prompt_tokens,
        None if usage is None else usage.completion_tokens,
    )
    return completion.text, snapshot_id


async def post_message(
    db: AsyncSession,
    session: ChatSession,
    content: str,
    provider: LLMProvider | None = None,
) -> tuple[ChatMessage, ChatMessage]:
    """Record a question and the assistant's answer as one exchange (FR-6.1).

    Both turns are written in a single transaction, so a conversation can never
    end up holding a question with no answer or an answer with no question.
    That also covers the 7.4 failure case: if the provider raises, nothing is
    added, and the question can simply be asked again rather than sitting in
    the history waiting for an answer that never came.
    """
    asked_at = _now()
    user_message = ChatMessage(
        session_id=session.id,
        role=ROLE_USER,
        content=content,
        created_at=asked_at,
    )
    reply, snapshot_id = await answer_question(db, session, content, provider)
    assistant_message = ChatMessage(
        session_id=session.id,
        role=ROLE_ASSISTANT,
        content=reply,
        kpi_context_snapshot_id=snapshot_id,
        # Strictly after the question, so the pair can never read back inverted
        # however fast the exchange was.
        created_at=asked_at + dt.timedelta(microseconds=1),
    )

    db.add_all([user_message, assistant_message])
    await db.commit()
    await db.refresh(user_message)
    await db.refresh(assistant_message)
    return user_message, assistant_message


async def delete_session(db: AsyncSession, session: ChatSession) -> None:
    """Delete a conversation and its messages (the FK cascades). The company's
    financial data is untouched."""
    await db.delete(session)
    await db.commit()
