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


# --- Board Report (task 8.2, FR-7.2) ---

REPORT_TYPE_BOARD = "board"

#: The reporting windows a board report can be asked for, and their length in
#: months. A board meets on a quarter; an investor asks for the year. Both are
#: **trailing** windows anchored on a month, not fiscal-calendar quarters — see
#: `reports.service.generate_board_report` for why.
BOARD_PERIODS: dict[str, int] = {"quarter": 3, "year": 12}


class PeriodTotals(BaseModel):
    """One reporting period's engine figures, and whether anything is recorded
    in it.

    `kpis` is a real `kpi_snapshots` row for that exact window — the board
    report states the previous period the same way it states the current one,
    off the same table, rather than one being a snapshot and the other a
    hand-rolled total. `has_data` false means nothing was recorded in the
    window: the figures are honest zeros, but zeros that mean "no record", not
    "no activity"."""

    start_month: str  # "YYYY-MM"
    end_month: str  # "YYYY-MM"
    period_start: dt.date
    period_end: dt.date
    has_data: bool
    kpis: KpiSnapshotRead
    transaction_count: int


class PeriodMovement(BaseModel):
    """The movement between the previous period and this one.

    Every field is one already-computed total minus another — the only
    arithmetic a report is allowed to do (architecture §4.1). Percentage growth
    is deliberately absent here: `kpis.revenue_growth_pct` already states it,
    measured against exactly the window `BoardReport.previous` describes, so a
    second percentage computed here could only agree or contradict."""

    revenue_change: Decimal
    expenses_change: Decimal
    net_change: Decimal
    burn_rate_change: Decimal


class CashPosition(BaseModel):
    """Cash at the start of the period, at the end, and the movement between.

    The first question a board asks. `net_change` is `closing − opening`, which
    is the period's net cash flow by construction — stated twice on purpose, so
    a reader can see the runway's numerator and the period's result reconcile."""

    opening_cash: Decimal
    closing_cash: Decimal
    net_change: Decimal


class WatchItem(BaseModel):
    """A flagged expense spike, grouped as the detection rule sees it — one
    category in one month (FR-3.6).

    A board reads exposure, not line items: "marketing ran ₹2L above trend in
    February" rather than four card charges. The grouping is a regrouping of
    the stored `is_flagged_anomaly` rows, not a new metric."""

    month: str  # "YYYY-MM"
    category_name: str
    total: Decimal
    transaction_count: int


class ScenarioSummary(BaseModel):
    """A saved what-if (FR-5.4), summarised for the board pack.

    Read verbatim out of `scenarios.result` as it was computed at save time —
    the same figures the Scenario Simulator showed. Nothing is re-run: a board
    paper says what the plan looked like when it was modelled, and re-deriving
    it against today's data would silently restate the plan."""

    id: uuid.UUID
    name: str
    created_at: dt.datetime
    period_start: dt.date
    period_end: dt.date
    revenue_change: Decimal
    expenses_change: Decimal
    net_cash_flow_change: Decimal
    burn_rate_change: Decimal
    baseline_runway_months: Decimal | None
    scenario_runway_months: Decimal | None


class BoardReport(BaseModel):
    """The Board Report (FR-7.2) — a period's trajectory, for a reader who
    wasn't in the building.

    Where the monthly report answers "what happened in July", this answers
    "where is this business heading": the period's KPIs against the equal-length
    period before it, the cash position at both ends, the month-by-month shape
    of the period, what the money is being spent on, what's being watched, and
    what plans have been modelled.

    Every figure is Financial Engine output — `kpis` on both periods are real
    `kpi_snapshots` rows — and **no LLM writes any part of it** (architecture
    §4.1 / §5.4)."""

    report_type: str = REPORT_TYPE_BOARD
    company: ReportCompany
    period: str  # "quarter" | "year"
    num_months: int
    generated_at: dt.datetime

    current: PeriodTotals
    previous: PeriodTotals
    movement: PeriodMovement
    cash: CashPosition

    monthly: list[MonthlyPerformanceRead]
    categories: list[CategoryLine]
    watch_items: list[WatchItem]
    scenarios: list[ScenarioSummary]


# --- Investor Readiness Summary (task 8.3, FR-7.3) ---

REPORT_TYPE_INVESTOR = "investor"

#: The window the summary is measured over: a trailing year of available data,
#: against the year before it. An investor's unit of assessment is the year, and
#: a shorter window would let one strong quarter stand in for a trajectory.
INVESTOR_WINDOW_MONTHS = 12


class RunRate(BaseModel):
    """What the business is earning *now*, annualised.

    `monthly` is the latest month with data — not the trailing year averaged —
    because a run-rate answers "what is this earning today" and averaging in the
    months before the company started selling understates it. The trailing-year
    total travels alongside in `window.kpis.total_revenue`, so a reader can see
    both rather than being handed the flattering one."""

    month: str  # "YYYY-MM" — the month the run-rate is taken from
    monthly: Decimal
    annualised: Decimal


class ReadinessCheck(BaseModel):
    """One graded readiness check (FR-7.3).

    `status` is `ready` / `attention` / `gap`, or `not_applicable` when the
    check couldn't be measured — a missing figure is never silently graded as a
    pass. `ready_at` and `attention_at` are the fixed thresholds the value was
    compared against, carried so the screen can state the rule rather than
    hard-code its own copy of it. Every check is higher-is-better.

    `detail` is template-filled prose built in `financial_engine.readiness` from
    the same figures as `value`; **no LLM writes it** (architecture §4.1)."""

    key: str
    label: str
    status: str
    value: Decimal | None
    unit: str  # "months" | "pct"
    ready_at: Decimal
    attention_at: Decimal
    detail: str


class InvestorSummary(BaseModel):
    """The Investor Readiness Summary (FR-7.3) — the metrics investors
    typically evaluate, and a fixed-rule checklist of how this company reads
    against them.

    Where the board report narrates a period, this one answers "would this
    survive a first diligence conversation": run-rate and its annualisation,
    the trailing year against the year before it, cash and burn efficiency, and
    six checks graded against stated thresholds.

    `overall_status` is the **weakest link**, not a score — no weighted total
    exists, because a single grade would imply a precision this data can't
    support and invite reading it as a valuation. Every figure is Financial
    Engine output and no LLM writes any part of it (architecture §4.1 / §5.4).
    """

    report_type: str = REPORT_TYPE_INVESTOR
    company: ReportCompany
    num_months: int = INVESTOR_WINDOW_MONTHS
    generated_at: dt.datetime

    window: PeriodTotals
    previous: PeriodTotals
    movement: PeriodMovement
    cash: CashPosition

    run_rate: RunRate
    burn_multiple: Decimal | None
    months_of_history: int
    months_with_revenue: int

    overall_status: str
    checks: list[ReadinessCheck]

    monthly: list[MonthlyPerformanceRead]
    categories: list[CategoryLine]
