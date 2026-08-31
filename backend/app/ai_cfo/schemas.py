"""Pydantic schemas for the AI CFO chat (tasks 7.1–7.3)."""

from __future__ import annotations

import datetime as dt
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatSessionCreate(BaseModel):
    """Start a conversation about one company's finances."""

    company_id: uuid.UUID


class ChatMessageCreate(BaseModel):
    """Ask the assistant something.

    Only the question travels — the caller never supplies a role or an answer.
    Both are decided server-side, so a client can't write words into the
    assistant's mouth or forge an answer into the stored history.
    """

    content: str = Field(min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("Message must not be blank.")
        return stripped


class ChatMessageRead(BaseModel):
    """One turn. `kpi_context_snapshot_id` names the precomputed KPI snapshot
    the assistant was given for this turn (7.2) — null for user turns, and for
    an assistant turn about a company with no transactions yet, where there are
    no computed figures to be grounded in."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    session_id: uuid.UUID
    role: str
    content: str
    kpi_context_snapshot_id: uuid.UUID | None
    created_at: dt.datetime


class ChatSessionRead(BaseModel):
    """A conversation, without its messages — the shape the session list uses.

    `preview` is the opening question, so the list is scannable without a
    request per session. There's no `title` column (schema §8): a conversation
    is named by what was asked in it, and storing a title as well would give two
    sources of truth for the same thing.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    user_id: uuid.UUID
    created_at: dt.datetime
    message_count: int
    preview: str | None


class ChatSessionDetail(ChatSessionRead):
    """A conversation with its full history, oldest first."""

    messages: list[ChatMessageRead]


class ChatTurnRead(BaseModel):
    """The result of asking a question: what you said, and what came back.

    Both are returned together so the client renders the stored rows rather
    than optimistically echoing its own copy of the question — what's on screen
    is then always what's in the database.
    """

    user_message: ChatMessageRead
    assistant_message: ChatMessageRead


# --- Assembled context (task 7.2, FR-6.2) ---


class FigureRead(BaseModel):
    """One precomputed figure as the assistant receives it: the rendered value,
    what it measures, and the caveat attached to this company's value."""

    key: str
    label: str
    value: str
    meaning: str
    note: str


class CfoContextRead(BaseModel):
    """Everything the AI CFO is given about a company for one answer (FR-6.2).

    Exposed rather than kept internal because it is the evidence for
    architecture §4.1: you can read exactly what the model gets, confirm every
    number in it is a stored `kpi_snapshots` value, and see that no transaction
    ever appears. `rendered` is the literal text block that goes into the
    prompt.
    """

    company_id: uuid.UUID
    company_name: str
    industry: str | None
    currency: str
    period_start: dt.date
    period_end: dt.date
    num_months: int
    snapshot_id: uuid.UUID
    computed_at: dt.datetime
    figures: list[FigureRead]
    rendered: str


class ChatContextRead(BaseModel):
    """The context for a company, or a plain statement of why there isn't one.

    A company with no transactions has no computed figures, and that is a
    normal state rather than an error — so it answers 200 with
    `available: false` and a reason a person can read, not a 404.
    """

    company_id: uuid.UUID
    available: bool
    unavailable_reason: str | None = None
    context: CfoContextRead | None = None


# --- The system prompt (task 7.3, FR-6.3 / FR-6.5) ---


class ChatPromptRead(BaseModel):
    """The standing instructions the assistant answers under.

    Exposed for the same reason the figures are (7.2): the claims this project
    makes about its AI — that it explains in plain language, never calculates,
    and never poses as a licensed professional — live in a block of text, and a
    reader should be able to check that text rather than take the claim on
    trust.

    `system_prompt` is the stable half, identical for every company and every
    question. `system_message` is the literal message that gets sent: the same
    instructions followed by this company's figures, or by a block saying it has
    none. The per-question part — conversation history and the question itself —
    isn't here because it isn't standing configuration; see
    `service.build_prompt`.
    """

    company_id: uuid.UUID
    system_prompt: str
    system_message: str
    max_history_messages: int
