"""Transactions-domain models — see `database/schema.md` §3–5.

* `Category` (§3): system default (`company_id IS NULL`) or company-specific.
* `UploadBatch` (§5): one row per CSV/XLSX import, tracks status + errors.
* `Transaction` (§4): a single financial line, from `upload` or `manual` entry.

`Transaction.type` is deliberately denormalized from `Category.type` (see the
locked-in design note in schema.md §4): it's set once at creation and never
follows a later category edit, keeping historical KPIs/reports stable.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(
            "type IN ('income', 'expense')", name="ck_categories_type"
        ),
    )

    # Nullable: NULL = system default category shared across all companies.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)


class UploadBatch(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One CSV/XLSX import. `created_at` is the upload time (schema's
    `uploaded_at`; standardised to the mixin's timestamps like every table)."""

    __tablename__ = "upload_batches"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_upload_batches_status",
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Newline-joined per-row validation issues, if any (FR-2.4 fleshed out in 3.4).
    error_log: Mapped[str | None] = mapped_column(Text, nullable=True)


class Transaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "transactions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('upload', 'manual')", name="ck_transactions_source"
        ),
        CheckConstraint(
            "type IN ('income', 'expense')", name="ck_transactions_type"
        ),
    )

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable until categorized (auto-categorization is task 4.1). Deleting a
    # category detaches its transactions rather than deleting them.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    upload_batch_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("upload_batches.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    date: Mapped[dt.date] = mapped_column(Date, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Stored as a positive magnitude; income/expense direction lives in `type`.
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    is_flagged_anomaly: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
