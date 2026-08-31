"""AI CFO chat endpoints (tasks 7.1–7.2).

The conversational interface, its persistence, and the KPI context an answer is
grounded in. **No LLM is called yet** — asking a question stores the question
and a clearly-labelled placeholder answer (see `ai_cfo.service`), now carrying
the id of the snapshot the real answer will be built from; the system prompt
(7.3) and the provider (7.4) come next.

Every route requires a session and is scoped to a company the caller owns,
answering 404 rather than 403 so existence isn't leaked.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai_cfo import context as context_module
from app.ai_cfo import service
from app.ai_cfo.models import ChatSession
from app.ai_cfo.schemas import (
    ChatContextRead,
    ChatMessageCreate,
    ChatMessageRead,
    ChatSessionCreate,
    ChatSessionDetail,
    ChatSessionRead,
    ChatTurnRead,
    CfoContextRead,
    FigureRead,
)
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.service import get_company_for_user
from app.core.database import get_db

router = APIRouter(prefix="/chat", tags=["ai-cfo"])


async def _require_company(
    company_id: uuid.UUID, user: User, db: AsyncSession
) -> None:
    if await get_company_for_user(db, company_id, user.id) is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )


async def _require_session(
    session_id: uuid.UUID, user: User, db: AsyncSession
) -> ChatSession:
    session = await service.get_session_for_user(db, session_id, user.id)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found."
        )
    return session


def _to_read(session: ChatSession, count: int, preview: str | None) -> ChatSessionRead:
    return ChatSessionRead(
        id=session.id,
        company_id=session.company_id,
        user_id=session.user_id,
        created_at=session.created_at,
        message_count=count,
        preview=preview,
    )


@router.post(
    "/sessions", response_model=ChatSessionRead, status_code=status.HTTP_201_CREATED
)
async def create_session(
    payload: ChatSessionCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionRead:
    """Start a new conversation about a company's finances (FR-6.1)."""
    await _require_company(payload.company_id, current_user, db)
    session = await service.create_session(db, payload.company_id, current_user.id)
    return _to_read(session, 0, None)


@router.get("/sessions", response_model=list[ChatSessionRead])
async def list_sessions(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ChatSessionRead]:
    """A company's conversations, newest first, each labelled by its opening
    question so the list is scannable without opening anything."""
    await _require_company(company_id, current_user, db)
    sessions = await service.list_sessions(db, company_id)
    summaries = await service.session_summaries(db, [s.id for s in sessions])
    return [_to_read(s, *summaries.get(s.id, (0, None))) for s in sessions]


@router.get("/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatSessionDetail:
    """One conversation with its full history, oldest turn first."""
    session = await _require_session(session_id, current_user, db)
    messages = await service.list_messages(db, session.id)
    preview = next((m.content for m in messages if m.role == "user"), None)
    return ChatSessionDetail(
        **_to_read(session, len(messages), preview).model_dump(),
        messages=[ChatMessageRead.model_validate(m) for m in messages],
    )


@router.post(
    "/sessions/{session_id}/messages",
    response_model=ChatTurnRead,
    status_code=status.HTTP_201_CREATED,
)
async def post_message(
    session_id: uuid.UUID,
    payload: ChatMessageCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatTurnRead:
    """Ask the assistant something (FR-6.1).

    Only the question is accepted — the role and the answer are both decided
    server-side, so a client can't forge an assistant turn into the history.
    Returns the exchange as stored.

    **Until 7.4 the answer is a fixed placeholder** that states the assistant
    isn't connected and quotes no figures. It is not, and must not be mistaken
    for, financial output. From 7.2 the assistant turn does carry
    `kpi_context_snapshot_id` — the figures the real answer will be built from.
    """
    session = await _require_session(session_id, current_user, db)
    user_message, assistant_message = await service.post_message(
        db, session, payload.content
    )
    return ChatTurnRead(
        user_message=ChatMessageRead.model_validate(user_message),
        assistant_message=ChatMessageRead.model_validate(assistant_message),
    )


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a conversation and its messages. Financial data is untouched."""
    session = await _require_session(session_id, current_user, db)
    await service.delete_session(db, session)


@router.get("/context", response_model=ChatContextRead)
async def get_context(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ChatContextRead:
    """Exactly what the AI CFO is given about this company (7.2, FR-6.2).

    This endpoint exists so the boundary in architecture §4.1 can be *seen*
    rather than taken on trust: every number in the response is a stored
    `kpi_snapshots` value, and no transaction appears anywhere in it. The
    assistant's answers quote from this and nothing else.

    A company with no transactions yet has no computed figures — that answers
    200 with `available: false`, because having entered no data is a normal
    state, not a missing resource.
    """
    await _require_company(company_id, current_user, db)
    assembled = await service.build_context(db, company_id)
    if assembled is None:
        return ChatContextRead(
            company_id=company_id,
            available=False,
            unavailable_reason=(
                "No transactions have been recorded for this company yet, so "
                "there are no calculated figures for the assistant to work "
                "from. Upload a statement or add entries manually first."
            ),
        )
    return ChatContextRead(
        company_id=company_id,
        available=True,
        context=CfoContextRead(
            company_id=assembled.company_id,
            company_name=assembled.company_name,
            industry=assembled.industry,
            currency=assembled.currency,
            period_start=assembled.period_start,
            period_end=assembled.period_end,
            num_months=assembled.num_months,
            snapshot_id=assembled.snapshot_id,
            computed_at=assembled.computed_at,
            figures=[FigureRead(**vars(f)) for f in assembled.figures],
            rendered=context_module.render(assembled),
        ),
    )
