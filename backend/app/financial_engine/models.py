"""Financial-engine models — see `database/schema.md` §6.

`KpiSnapshot` (§6): precomputed KPI values stored per company per period. This
is the table the AI CFO reads from; it never derives these numbers itself
(architecture §4.1). All figures are computed deterministically by
`financial_engine` and persisted here (task 4.3, FR-4.1–4.5).

Nullability note (deviation from schema.md, which only marked `runway_months`
nullable): the margin and growth columns are also nullable, because each has an
undefined case — margins when revenue is 0, growth when there's no prior-period
revenue to compare against. Storing NULL is more honest than a bogus 0.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class KpiSnapshot(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One precomputed KPI set for a company over [period_start, period_end].

    `created_at` is the compute time (schema's `computed_at`, standardised to the
    mixin's timestamps like every other table)."""

    __tablename__ = "kpi_snapshots"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start: Mapped[dt.date] = mapped_column(Date, nullable=False)
    period_end: Mapped[dt.date] = mapped_column(Date, nullable=False)

    total_revenue: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    total_expenses: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    net_cash_flow: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    burn_rate: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    # Nullable when the company isn't burning cash (profitable) or has none left.
    runway_months: Mapped[float | None] = mapped_column(Numeric(6, 2), nullable=True)
    # Nullable when revenue is 0 (margin undefined).
    gross_margin_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    operating_margin_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
    # Nullable when there's no prior-period revenue to grow from.
    revenue_growth_pct: Mapped[float | None] = mapped_column(
        Numeric(6, 2), nullable=True
    )
