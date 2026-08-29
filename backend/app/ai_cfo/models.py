"""AI CFO chat models — see `database/schema.md` §8–9.

Two tables backing the conversational interface (task 7.1, FR-6.1):

* `ChatSession` — one conversation, scoped to a company and the user who
  started it.
* `ChatMessage` — one turn in that conversation, `user` or `assistant`.

`kpi_context_snapshot_id` records **which precomputed KPI snapshot was passed
to the model** for a given assistant turn. It stays NULL through 7.1 (no
context is assembled yet — that's 7.2) but the column exists from the start
because it is the audit trail for the architecture's central rule: the
assistant only ever *receives* figures the Financial Engine computed, and never
derives one itself (architecture §4.1, SRS FR-6.6). Being able to point at the
exact snapshot behind an answer is what makes that rule checkable rather than
merely asserted.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin

# The two speakers in a conversation (mirrors the DB check constraint).
ROLE_USER = "user"
ROLE_ASSISTANT = "assistant"
MESSAGE_ROLES = (ROLE_USER, ROLE_ASSISTANT)


class ChatSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One conversation about one company's finances.

    `created_at` is the start time (schema's `started_at`, standardised to the
    mixin's timestamps like every other table).

    Both foreign keys cascade: deleting a company or a user removes their
    conversations. A chat is a record of a discussion *about* that data, so it
    has no meaning once the data or the person is gone.
    """

    __tablename__ = "chat_sessions"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )


class ChatMessage(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One turn in a conversation. Ordered by `created_at` within a session."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_chat_messages_role"
        ),
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)

    # Which precomputed KPI snapshot was given to the model for this turn.
    # NULL for user turns, and for every turn until 7.2 assembles context.
    # SET NULL on delete: losing a snapshot must not delete the conversation.
    kpi_context_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kpi_snapshots.id", ondelete="SET NULL"), nullable=True
    )
