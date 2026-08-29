"""AI CFO chat service (task 7.1, FR-6.1) — sessions and message history.

**No LLM is called here yet.** 7.1 is deliberately the interface and its
persistence: the chat screen, the two tables, and owner-scoped access. What
makes an answer *useful* arrives in the tasks after it — context assembly from
`kpi_snapshots` (7.2), the plain-language system prompt and advisory disclaimer
(7.3), and the swappable provider (7.4).

**The placeholder reply (decided in 7.1).** A question still has to produce an
assistant turn, otherwise the conversation is one-sided and neither the UI nor
the persistence can be exercised end to end. So `answer_question` writes a
fixed, clearly-labelled placeholder. It is deliberately inert: it states that
the assistant isn't connected yet, and it contains **no figures, no advice and
no reference to the company's data**. Storing a plausible-sounding stub answer
would be far worse than storing an obviously unfinished one — a demo could show
it and a reader could believe it. 7.4 replaces `answer_question` with the real
provider call; nothing else in this module changes.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_cfo.models import ROLE_ASSISTANT, ROLE_USER, ChatMessage, ChatSession
from app.companies.models import Company

# The stub answer. No numbers, no advice — see the module docstring.
PLACEHOLDER_REPLY = (
    "The AI CFO isn't connected yet, so I can't answer that one properly.\n\n"
    "What's working right now is the conversation itself — your question was "
    "saved and this history will still be here when you come back. Answering "
    "with your actual figures needs three more pieces: reading your "
    "precomputed KPIs as context, the plain-language prompt, and the model "
    "connection.\n\n"
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


def answer_question(question: str) -> tuple[str, uuid.UUID | None]:
    """Produce the assistant's reply and the KPI snapshot it was grounded in.

    **7.1 stub** — returns the fixed placeholder and no snapshot. The signature
    is the one the real implementation needs, so 7.2–7.4 fill this in without
    disturbing `post_message` or the router. `question` is unused for now and
    deliberately not inspected: guessing at intent here would be the beginning
    of the assistant reasoning about finances on its own.
    """
    return PLACEHOLDER_REPLY, None


async def post_message(
    db: AsyncSession, session: ChatSession, content: str
) -> tuple[ChatMessage, ChatMessage]:
    """Record a question and the assistant's answer as one exchange (FR-6.1).

    Both turns are written in a single transaction, so a conversation can never
    end up holding a question with no answer or an answer with no question.
    """
    asked_at = _now()
    user_message = ChatMessage(
        session_id=session.id,
        role=ROLE_USER,
        content=content,
        created_at=asked_at,
    )
    reply, snapshot_id = answer_question(content)
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
