"""Report schemas (Phase 8, FR-7.x).

The shape of a generated report. Everything numeric here is a value the
Financial Engine already computed — reports **assemble**, they never calculate,
and no LLM writes any part of one (architecture §4.1 / §5.4). That is why the
KPI block is literally `KpiSnapshotRead`: a monthly report quotes the same
stored `kpi_snapshots` row the dashboard's tiles and the AI CFO's context read,
rather than a second set of numbers that happen to agree today.

Figures travel as raw `Decimal`s, not pre-formatted strings, for the same
reason every other endpoint does — the frontend renders them through
`lib/format.ts` so a rupee reads identically on every screen. (Server-side
rendering via `core/formatting.py` is 8.4's business, when a PDF has to draw
the text itself.)
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel

from app.financial_engine.schemas import KpiSnapshotRead, MonthlyPerformanceRead

REPORT_TYPE_MONTHLY = "monthly"


class ReportCompany(BaseModel):
    """Who the report is about. Carried on the report itself so a saved or
    exported copy still names its subject once it's away from the app."""

    id: uuid.UUID
    name: str
    industry: str | None
    currency: str


class CategoryLine(BaseModel):
    """One category's line in the breakdown. `name` is resolved server-side —
    "Uncategorized" for transactions the rules couldn't place, which are shown
    rather than dropped so the lines still add up to the totals above them.

    `share_pct` is a share of that line's **own type** (an expense as a % of all
    expenses), null when that type had no total to take a share of."""

    category_id: uuid.UUID | None
    name: str
    type: str  # "income" | "expense"
    total: Decimal
    share_pct: Decimal | None
    transaction_count: int


class MonthComparison(BaseModel):
    """The month before this one, and the movement between them.

    `has_data` is false when nothing was recorded in the prior month — the
    changes are then differences against zero, which is arithmetically true but
    means "we have no record of that month", not "the business did nothing".
    The flag lets the screen say which one it is."""

    month: str  # "YYYY-MM"
    has_data: bool
    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    revenue_change: Decimal
    expenses_change: Decimal
    net_change: Decimal


class ReportAnomaly(BaseModel):
    """A flagged expense inside the reported month (FR-3.6), listed so the
    report surfaces what needs attention rather than only what happened."""

    id: uuid.UUID
    date: dt.date
    description: str | None
    category_name: str
    amount: Decimal


class MonthlyReport(BaseModel):
    """The Monthly Financial Report (FR-7.1) — revenue, expenses, cash flow and
    KPIs for one calendar month, plus what a founder needs to read them: where
    the money went, how the month moved against the one before it, the recent
    trend, and anything flagged.

    `kpis.id` is the `kpi_snapshots` row behind the headline figures, the same
    traceability handle `chat_messages.kpi_context_snapshot_id` gives an answer.
    """

    report_type: str = REPORT_TYPE_MONTHLY
    company: ReportCompany
    month: str  # "YYYY-MM"
    period_start: dt.date
    period_end: dt.date
    generated_at: dt.datetime

    kpis: KpiSnapshotRead
    transaction_count: int
    income_count: int
    expense_count: int
    closing_cash: Decimal

    categories: list[CategoryLine]
    comparison: MonthComparison
    trend: list[MonthlyPerformanceRead]
    anomalies: list[ReportAnomaly]
