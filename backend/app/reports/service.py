"""Report generation (Phase 8, FR-7.x) — 8.1's Monthly Financial Report,
8.2's Board Report and 8.3's Investor Readiness Summary.

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
rather than as paperwork. The investor summary's trailing year is the same
window rule at a longer length.

**Judging is not assembling either.** The investor summary grades six checks
against fixed thresholds, and that grading lives in
`financial_engine/readiness.py` — a pure, DB-free module beside `anomaly.py`,
which does the same kind of thing with the same kind of fixed rule. Deciding
what a four-month runway *means* is a rule over engine output; this module only
gathers the inputs and carries the verdicts out.
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
from app.financial_engine.readiness import (
    ReadinessInputs,
    annualised_run_rate,
    burn_multiple,
    evaluate_readiness,
    months_of_history,
    overall_status,
)
from app.financial_engine.service import (
    cash_on_hand,
    company_category_breakdown,
    company_cash_flow,
    company_history,
    company_totals,
    earliest_transaction_month,
    latest_transaction_month,
    snapshot_for_period,
)
from app.reports.schemas import (
    BOARD_PERIODS,
    INVESTOR_WINDOW_MONTHS,
    BoardReport,
    CashPosition,
    CategoryLine,
    InvestorSummary,
    MonthComparison,
    MonthlyReport,
    PeriodMovement,
    PeriodTotals,
    ReadinessCheck,
    ReportAnomaly,
    ReportCompany,
    RunRate,
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


def _report_company(company: Company) -> ReportCompany:
    """Who the report is about, carried on the report itself so an exported
    copy still names its subject once it's away from the app."""
    return ReportCompany(
        id=company.id,
        name=company.name,
        industry=company.industry,
        currency=company.currency,
    )


def _category_lines(breakdown, category_names: dict[uuid.UUID, str]):
    """The engine's category totals as report lines, with ids resolved to names.

    Shared by all three reports (8.3 was the third caller): three reports
    resolving "Uncategorized" separately is three chances for one of them to
    quietly drop the bucket and stop adding up to its own totals."""
    return [
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
    ]


def _performance_series(series) -> list[MonthlyPerformanceRead]:
    """The engine's gap-filled monthly series as report rows."""
    return [
        MonthlyPerformanceRead(
            month=m.month,
            revenue=m.revenue,
            expenses=m.expenses,
            net_cash_flow=m.net_cash_flow,
            margin_pct=m.margin_pct,
        )
        for m in series
    ]


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
        company=_report_company(company),
        month=_month_key(year, mo),
        period_start=period_start,
        period_end=period_end,
        generated_at=dt.datetime.now(dt.timezone.utc),
        kpis=KpiSnapshotRead.model_validate(snapshot),
        transaction_count=totals.income_count + totals.expense_count,
        income_count=totals.income_count,
        expense_count=totals.expense_count,
        closing_cash=closing_cash,
        categories=_category_lines(breakdown, category_names),
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
        trend=_performance_series(trend),
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
        company=_report_company(company),
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
        monthly=_performance_series(monthly),
        categories=_category_lines(breakdown, category_names),
        watch_items=await _watch_items(
            db, company.id, period_start, period_end, category_names
        ),
        scenarios=await _scenario_summaries(db, company.id),
    )


# --- Investor Readiness Summary (task 8.3, FR-7.3) ---


async def _months_with_revenue(db: AsyncSession, company_id: uuid.UUID) -> int:
    """How many calendar months on record have any revenue in them.

    Counted over the company's whole history rather than the reported window,
    so that a nine-month-old company isn't marked inconsistent for the three
    months before it existed. Months are the engine's own cash-flow buckets —
    only months with transactions appear, which is exactly what's being counted.
    """
    months = await company_cash_flow(db, company_id)
    return sum(1 for m in months if m.inflow > Decimal("0"))


def _categorized_expense_pct(lines: list[CategoryLine]) -> Decimal | None:
    """Share of expense **value** carrying a category, as a percentage.

    By value rather than by count, because one uncategorized payroll run matters
    more to a reader than forty uncategorized coffees. None when there are no
    expenses to take a share of."""
    total = sum((line.total for line in lines if line.type == "expense"), Decimal("0"))
    if total <= Decimal("0"):
        return None
    placed = sum(
        (
            line.total
            for line in lines
            if line.type == "expense" and line.category_id is not None
        ),
        Decimal("0"),
    )
    return (placed * 100 / total).quantize(Decimal("0.01"))


async def generate_investor_summary(
    db: AsyncSession,
    company: Company,
    end_month: tuple[int, int] | None = None,
) -> InvestorSummary:
    """Build the Investor Readiness Summary (FR-7.3).

    The metrics investors typically evaluate, plus a fixed-threshold checklist
    of how the company reads against them: run-rate and its annualisation, the
    trailing year against the year before it, cash at both ends, burn
    efficiency, and six graded checks.

    **The window is a trailing year of available data**, anchored like every
    other window in this codebase (see `generate_board_report`). A year is the
    investor's unit of assessment; a shorter window would let one strong quarter
    stand in for a trajectory. `end_month` names a different anchor for the same
    reason it does on the board report.

    The grading lives in `financial_engine.readiness`, not here — a report
    assembles, and deciding what a runway of four months *means* is a rule over
    engine output, testable without a database and without this module. Raises
    `NoFinancialData` when the company has no transactions at all.
    """
    if end_month is None:
        end_month = await latest_transaction_month(db, company.id)
        if end_month is None:
            raise NoFinancialData
    end_year, end_mo = end_month

    period_start, period_end = board_period_bounds(
        end_year, end_mo, INVESTOR_WINDOW_MONTHS
    )
    prev_start, prev_end = previous_period_bounds(period_start, INVESTOR_WINDOW_MONTHS)

    window = await _period_totals(db, company.id, period_start, period_end)
    previous = await _period_totals(db, company.id, prev_start, prev_end)

    opening_cash = await cash_on_hand(
        db, company.id, period_start - dt.timedelta(days=1)
    )
    closing_cash = await cash_on_hand(db, company.id, period_end)

    categories = await list_categories(db, company.id)
    category_names = {c.id: c.name for c in categories}
    breakdown = await company_category_breakdown(
        db, company.id, period_start, period_end
    )
    category_lines = _category_lines(breakdown, category_names)

    monthly, _ = await company_history(
        db, company.id, INVESTOR_WINDOW_MONTHS, (end_year, end_mo)
    )
    series = _performance_series(monthly)
    # The anchor month is the latest month *with data* by construction, so the
    # last row of the gap-filled series is the run-rate month — never a zero
    # month padded onto the end.
    latest = series[-1]

    # `burn_rate` is a per-month figure; the window's total burn is it across
    # the window, which is `expenses − revenue` — restated from the engine's own
    # net rather than recomputed from transactions.
    net_burn = -window.kpis.net_cash_flow

    first_month = await earliest_transaction_month(db, company.id)
    # `first_month` is not None here: the anchor came from a real transaction.
    history_months = months_of_history(
        dt.date(first_month[0], first_month[1], 1), period_end
    )
    revenue_months = await _months_with_revenue(db, company.id)

    checks = evaluate_readiness(
        ReadinessInputs(
            months_of_history=history_months,
            months_with_revenue=revenue_months,
            runway_months=window.kpis.runway_months,
            is_burning=net_burn > Decimal("0"),
            revenue_growth_pct=window.kpis.revenue_growth_pct,
            operating_margin_pct=window.kpis.operating_margin_pct,
            categorized_expense_pct=_categorized_expense_pct(category_lines),
        )
    )

    return InvestorSummary(
        company=_report_company(company),
        generated_at=dt.datetime.now(dt.timezone.utc),
        window=window,
        previous=previous,
        movement=PeriodMovement(
            revenue_change=window.kpis.total_revenue - previous.kpis.total_revenue,
            expenses_change=(
                window.kpis.total_expenses - previous.kpis.total_expenses
            ),
            net_change=window.kpis.net_cash_flow - previous.kpis.net_cash_flow,
            burn_rate_change=window.kpis.burn_rate - previous.kpis.burn_rate,
        ),
        cash=CashPosition(
            opening_cash=opening_cash,
            closing_cash=closing_cash,
            net_change=closing_cash - opening_cash,
        ),
        run_rate=RunRate(
            month=latest.month,
            monthly=latest.revenue,
            annualised=annualised_run_rate(latest.revenue),
        ),
        burn_multiple=burn_multiple(
            net_burn, window.kpis.total_revenue, previous.kpis.total_revenue
        ),
        months_of_history=history_months,
        months_with_revenue=revenue_months,
        overall_status=overall_status(checks),
        checks=[
            ReadinessCheck.model_validate(check, from_attributes=True)
            for check in checks
        ],
        monthly=series,
        categories=category_lines,
    )


__all__ = [
    "BOARD_PERIODS",
    "BOARD_SCENARIO_LIMIT",
    "INVESTOR_WINDOW_MONTHS",
    "TREND_MONTHS",
    "UNCATEGORIZED",
    "NoFinancialData",
    "board_period_bounds",
    "generate_board_report",
    "generate_investor_summary",
    "generate_monthly_report",
    "month_bounds",
    "parse_month",
    "previous_month",
    "previous_period_bounds",
]
