"""Report generation (Phase 8, FR-7.x) — 8.1's Monthly Financial Report and
8.2's Board Report.

**A report is an assembly, not a calculation.** Every figure in one is pulled
from the Financial Engine — the `kpi_snapshots` row for the month, the same
totals the dashboard sums, the same gap-filled history series it plots, the same
`is_flagged_anomaly` column it highlights. Nothing here does arithmetic on money
beyond subtracting one already-computed total from another for the
month-over-month movement, and no LLM writes any part of a report (architecture
§4.1 / §5.4). That matters more for reports than anywhere else: a report is the
artefact that leaves the building, so a number in it disagreeing with the
dashboard would be a defect nobody catches until a board meeting.

**Reports are generated on demand, not stored.** `schema.md` §10 defines a
`reports` table keyed on a `file_path`, which is a record of an exported *file*;
until 8.4 produces one there is no file to point at. A monthly report is a pure
function of the company's transactions, so regenerating it costs one round of
aggregation and can never go stale — whereas a stored copy could quietly
disagree with the data it claims to describe. The table lands with the export
that needs it.

**The month is a whole calendar month.** Not a rolling 30 days and not the
fiscal-year offset in `companies.fiscal_year_start_month`: "the July report"
must mean 1–31 July to everyone who reads it. The KPI snapshot is generated for
exactly that window, so the month's `revenue_growth_pct` is growth against the
preceding month (the equal-length prior window) and `burn_rate` is that single
month's net outflow rather than an average over a longer period.

**A board period is a trailing window**, anchored on the latest month with data
(or a month named explicitly), because that is what "the last quarter" means
everywhere else in this codebase — *of available data*. Books kept in arrears
would otherwise produce a quarter two-thirds empty, which reads as a collapse
rather than as paperwork.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid

from decimal import Decimal

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.financial_engine.calculations import month_range
from app.financial_engine.schemas import KpiSnapshotRead, MonthlyPerformanceRead
from app.financial_engine.service import (
    cash_on_hand,
    company_category_breakdown,
    company_history,
    company_totals,
    latest_transaction_month,
    snapshot_for_period,
)
from app.reports.schemas import (
    BOARD_PERIODS,
    BoardReport,
    CashPosition,
    CategoryLine,
    MonthComparison,
    MonthlyReport,
    PeriodMovement,
    PeriodTotals,
    ReportAnomaly,
    ReportCompany,
    ScenarioSummary,
    WatchItem,
)
from app.scenarios.schemas import ScenarioSimulationRead
from app.scenarios.service import list_scenarios
from app.transactions.models import Transaction
from app.transactions.service import list_categories

# How many months of context the monthly report carries. Six is enough to see a
# trend forming around the reported month without turning a one-month report
# into the twelve-month dashboard the reader already has.
TREND_MONTHS = 6

# Shown for transactions the categorization rules couldn't place. They are
# reported, never dropped — see `CategoryLine`.
UNCATEGORIZED = "Uncategorized"


class NoFinancialData(Exception):
    """The company has no transactions, so there is nothing to report on.

    Distinct from "the reported month was quiet": a month with no activity is a
    real, reportable finding (zeros, honestly stated), whereas a company with no
    data at all has no months to choose from and nothing to say."""


def parse_month(text: str) -> tuple[int, int]:
    """`"2026-07"` → `(2026, 7)`. Raises `ValueError` on anything else."""
    year_str, _, month_str = text.partition("-")
    if len(year_str) != 4 or len(month_str) != 2:
        raise ValueError("month must be in YYYY-MM format.")
    year, month = int(year_str), int(month_str)
    if not 1 <= month <= 12:
        raise ValueError("month must be in YYYY-MM format.")
    return year, month


def month_bounds(year: int, month: int) -> tuple[dt.date, dt.date]:
    """The first and last calendar day of a month."""
    last_day = calendar.monthrange(year, month)[1]
    return dt.date(year, month, 1), dt.date(year, month, last_day)


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _month_key(year: int, month: int) -> str:
    return f"{year:04d}-{month:02d}"


async def _anomalies(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
    category_names: dict[uuid.UUID, str],
) -> list[ReportAnomaly]:
    """The month's flagged expenses, largest first.

    Read as stored rather than re-detected: generating a report is a read, and
    a GET that rewrites `is_flagged_anomaly` would mean two people opening the
    same report could see different flags. Detection is re-run from the screens
    that own it (the dashboard, `POST /transactions/detect-anomalies`)."""
    result = await db.execute(
        select(Transaction)
        .where(
            Transaction.company_id == company_id,
            Transaction.is_flagged_anomaly.is_(True),
            Transaction.date >= period_start,
            Transaction.date <= period_end,
        )
        .order_by(Transaction.amount.desc(), Transaction.date)
    )
    return [
        ReportAnomaly(
            id=txn.id,
            date=txn.date,
            description=txn.description,
            category_name=(
                category_names.get(txn.category_id, UNCATEGORIZED)
                if txn.category_id is not None
                else UNCATEGORIZED
            ),
            amount=txn.amount,
        )
        for txn in result.scalars().all()
    ]


async def generate_monthly_report(
    db: AsyncSession,
    company: Company,
    month: tuple[int, int] | None = None,
) -> MonthlyReport:
    """Build the Monthly Financial Report for one calendar month (FR-7.1).

    `month` defaults to the latest month the company has data for — "this
    month" is nearly always empty for a company whose books are kept in
    arrears, and a report of zeros is a worse default than the last real one.
    Raises `NoFinancialData` when the company has no transactions at all.
    """
    if month is None:
        month = await latest_transaction_month(db, company.id)
        if month is None:
            raise NoFinancialData
    year, mo = month
    period_start, period_end = month_bounds(year, mo)

    # The month's headline figures, from the same get-or-create path the
    # dashboard and the AI CFO use — so all three quote one snapshot, not three.
    snapshot = await snapshot_for_period(db, company.id, period_start, period_end)

    totals = await company_totals(db, company.id, period_start, period_end)
    closing_cash = await cash_on_hand(db, company.id, period_end)

    categories = await list_categories(db, company.id)
    category_names = {c.id: c.name for c in categories}
    breakdown = await company_category_breakdown(
        db, company.id, period_start, period_end
    )

    prev_year, prev_mo = previous_month(year, mo)
    prev_start, prev_end = month_bounds(prev_year, prev_mo)
    prev_totals = await company_totals(db, company.id, prev_start, prev_end)

    trend, _ = await company_history(db, company.id, TREND_MONTHS, (year, mo))

    return MonthlyReport(
        company=ReportCompany(
            id=company.id,
            name=company.name,
            industry=company.industry,
            currency=company.currency,
        ),
        month=_month_key(year, mo),
        period_start=period_start,
        period_end=period_end,
        generated_at=dt.datetime.now(dt.timezone.utc),
        kpis=KpiSnapshotRead.model_validate(snapshot),
        transaction_count=totals.income_count + totals.expense_count,
        income_count=totals.income_count,
        expense_count=totals.expense_count,
        closing_cash=closing_cash,
        categories=[
            CategoryLine(
                category_id=line.group,
                name=(
                    category_names.get(line.group, UNCATEGORIZED)
                    if line.group is not None
                    else UNCATEGORIZED
                ),
                type=line.type,
                total=line.total,
                share_pct=line.share_pct,
                transaction_count=line.count,
            )
            for line in breakdown
        ],
        comparison=MonthComparison(
            month=_month_key(prev_year, prev_mo),
            has_data=(prev_totals.income_count + prev_totals.expense_count) > 0,
            total_revenue=prev_totals.total_income,
            total_expenses=prev_totals.total_expenses,
            net_cash_flow=prev_totals.net,
            revenue_change=totals.total_income - prev_totals.total_income,
            expenses_change=totals.total_expenses - prev_totals.total_expenses,
            net_change=totals.net - prev_totals.net,
        ),
        trend=[
            MonthlyPerformanceRead(
                month=m.month,
                revenue=m.revenue,
                expenses=m.expenses,
                net_cash_flow=m.net_cash_flow,
                margin_pct=m.margin_pct,
            )
            for m in trend
        ],
        anomalies=await _anomalies(
            db, company.id, period_start, period_end, category_names
        ),
    )



# --- Board Report (task 8.2, FR-7.2) ---

# How many saved scenarios (FR-5.4) a board report carries. A board pack shows
# the plans currently on the table, not an archive — the newest few are the ones
# still being argued about.
BOARD_SCENARIO_LIMIT = 3


def board_period_bounds(
    end_year: int, end_month: int, num_months: int
) -> tuple[dt.date, dt.date]:
    """The trailing `num_months`-month window ending at `end_year`-`end_month`,
    whole calendar months at both ends."""
    start_year, start_mo = month_range(end_year, end_month, num_months)[0]
    return (
        dt.date(start_year, start_mo, 1),
        month_bounds(end_year, end_month)[1],
    )


def previous_period_bounds(
    period_start: dt.date, num_months: int
) -> tuple[dt.date, dt.date]:
    """The `num_months` calendar months immediately before `period_start`.

    Calendar-aligned rather than the engine's day-counted `previous_window`,
    matching the monthly report's previous-month block: a board compares Q3
    against Q2, and a window labelled "30 Jan – 30 Apr" because a quarter
    happens to be three days longer than the one before it is a window nobody
    asked for. The engine's `revenue_growth_pct` still uses its own equal-length
    day window internally; the two coincide whenever the periods have the same
    number of days (always for the 12-month period) and differ by at most a few
    days of a shoulder month otherwise.
    """
    prev_end = period_start - dt.timedelta(days=1)
    return board_period_bounds(prev_end.year, prev_end.month, num_months)


async def _period_totals(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
) -> PeriodTotals:
    """One period's figures, stated off a real `kpi_snapshots` row.

    Both periods in a board report go through here, so "this quarter" and "last
    quarter" are the same kind of object computed the same way — a comparison
    where one side is a snapshot and the other a hand-rolled total is a
    comparison of two different things."""
    totals = await company_totals(db, company_id, period_start, period_end)
    snapshot = await snapshot_for_period(db, company_id, period_start, period_end)
    count = totals.income_count + totals.expense_count
    return PeriodTotals(
        start_month=_month_key(period_start.year, period_start.month),
        end_month=_month_key(period_end.year, period_end.month),
        period_start=period_start,
        period_end=period_end,
        has_data=count > 0,
        kpis=KpiSnapshotRead.model_validate(snapshot),
        transaction_count=count,
    )


async def _watch_items(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
    category_names: dict[uuid.UUID, str],
) -> list[WatchItem]:
    """Flagged expenses in the period, grouped the way the detection rule sees
    them — one category in one month — largest first.

    Read as stored, never re-detected, for the same reason the monthly report
    reads them: a `GET` that rewrote `is_flagged_anomaly` would let two people
    opening the same board pack see different flags."""
    result = await db.execute(
        select(Transaction).where(
            Transaction.company_id == company_id,
            Transaction.is_flagged_anomaly.is_(True),
            Transaction.date >= period_start,
            Transaction.date <= period_end,
        )
    )
    buckets: dict[tuple[str, str], list] = {}
    for txn in result.scalars().all():
        name = (
            category_names.get(txn.category_id, UNCATEGORIZED)
            if txn.category_id is not None
            else UNCATEGORIZED
        )
        key = (_month_key(txn.date.year, txn.date.month), name)
        bucket = buckets.setdefault(key, [Decimal("0"), 0])
        bucket[0] += txn.amount
        bucket[1] += 1

    items = [
        WatchItem(month=month, category_name=name, total=total, transaction_count=n)
        for (month, name), (total, n) in buckets.items()
    ]
    # Largest exposure first; month then name as a stable tiebreak so two
    # renders of one report can't reorder.
    items.sort(key=lambda i: (-i.total, i.month, i.category_name))
    return items


async def _scenario_summaries(
    db: AsyncSession, company_id: uuid.UUID
) -> list[ScenarioSummary]:
    """The newest saved scenarios (FR-5.4), summarised from their stored
    results.

    Nothing is re-run: `scenarios.result` holds the comparison as computed at
    save time, and a board paper should say what the plan looked like when it
    was modelled. A row whose stored result predates the current shape is
    skipped rather than guessed at."""
    summaries: list[ScenarioSummary] = []
    for scenario in await list_scenarios(db, company_id):
        try:
            result = ScenarioSimulationRead.model_validate(scenario.result)
        except ValidationError:
            continue
        summaries.append(
            ScenarioSummary(
                id=scenario.id,
                name=scenario.name,
                created_at=scenario.created_at,
                period_start=result.period_start,
                period_end=result.period_end,
                revenue_change=result.deltas.total_revenue,
                expenses_change=result.deltas.total_expenses,
                net_cash_flow_change=result.deltas.net_cash_flow,
                burn_rate_change=result.deltas.burn_rate,
                baseline_runway_months=result.baseline.runway_months,
                scenario_runway_months=result.scenario.runway_months,
            )
        )
        if len(summaries) == BOARD_SCENARIO_LIMIT:
            break
    return summaries


async def generate_board_report(
    db: AsyncSession,
    company: Company,
    period: str = "quarter",
    end_month: tuple[int, int] | None = None,
) -> BoardReport:
    """Build the Board Report for a trailing quarter or year (FR-7.2).

    Where the monthly report answers "what happened in July", this answers
    "where is this heading" for someone who wasn't in the building: the
    period's KPIs beside the equal-length period before them, cash at both
    ends, the month-by-month shape, the cost structure, what's flagged, and
    which plans have been modelled.

    **A trailing window, not a fiscal quarter.** `end_month` defaults to the
    latest month with data and the window is the `num_months` calendar months
    ending there, for the same reason every other "last N months" in this
    codebase means *of available data*: books kept in arrears would otherwise
    produce a quarter that is two-thirds empty and read as a collapse. A
    calendar or fiscal quarter is still available by naming its last month
    explicitly (`end_month=2026-03` with `period=quarter` is Jan–Mar).

    Raises `NoFinancialData` when the company has no transactions at all.
    """
    num_months = BOARD_PERIODS[period]
    if end_month is None:
        end_month = await latest_transaction_month(db, company.id)
        if end_month is None:
            raise NoFinancialData
    end_year, end_mo = end_month

    period_start, period_end = board_period_bounds(end_year, end_mo, num_months)
    prev_start, prev_end = previous_period_bounds(period_start, num_months)

    current = await _period_totals(db, company.id, period_start, period_end)
    previous = await _period_totals(db, company.id, prev_start, prev_end)

    # Cash at both ends of the period. Opening cash is the closing cash of the
    # day before, so `closing − opening` is the period's net cash flow by
    # construction — the report states the runway's numerator and the period's
    # result in a way a reader can reconcile.
    opening_cash = await cash_on_hand(
        db, company.id, period_start - dt.timedelta(days=1)
    )
    closing_cash = await cash_on_hand(db, company.id, period_end)

    categories = await list_categories(db, company.id)
    category_names = {c.id: c.name for c in categories}
    breakdown = await company_category_breakdown(
        db, company.id, period_start, period_end
    )

    monthly, _ = await company_history(db, company.id, num_months, (end_year, end_mo))

    return BoardReport(
        company=ReportCompany(
            id=company.id,
            name=company.name,
            industry=company.industry,
            currency=company.currency,
        ),
        period=period,
        num_months=num_months,
        generated_at=dt.datetime.now(dt.timezone.utc),
        current=current,
        previous=previous,
        movement=PeriodMovement(
            revenue_change=current.kpis.total_revenue - previous.kpis.total_revenue,
            expenses_change=(
                current.kpis.total_expenses - previous.kpis.total_expenses
            ),
            net_change=current.kpis.net_cash_flow - previous.kpis.net_cash_flow,
            burn_rate_change=current.kpis.burn_rate - previous.kpis.burn_rate,
        ),
        cash=CashPosition(
            opening_cash=opening_cash,
            closing_cash=closing_cash,
            net_change=closing_cash - opening_cash,
        ),
        monthly=[
            MonthlyPerformanceRead(
                month=m.month,
                revenue=m.revenue,
                expenses=m.expenses,
                net_cash_flow=m.net_cash_flow,
                margin_pct=m.margin_pct,
            )
            for m in monthly
        ],
        categories=[
            CategoryLine(
                category_id=line.group,
                name=(
                    category_names.get(line.group, UNCATEGORIZED)
                    if line.group is not None
                    else UNCATEGORIZED
                ),
                type=line.type,
                total=line.total,
                share_pct=line.share_pct,
                transaction_count=line.count,
            )
            for line in breakdown
        ],
        watch_items=await _watch_items(
            db, company.id, period_start, period_end, category_names
        ),
        scenarios=await _scenario_summaries(db, company.id),
    )


__all__ = [
    "BOARD_PERIODS",
    "BOARD_SCENARIO_LIMIT",
    "TREND_MONTHS",
    "UNCATEGORIZED",
    "NoFinancialData",
    "board_period_bounds",
    "generate_board_report",
    "generate_monthly_report",
    "month_bounds",
    "parse_month",
    "previous_month",
    "previous_period_bounds",
]
