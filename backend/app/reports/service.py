"""Report generation (Phase 8, FR-7.x). Task 8.1: the Monthly Financial Report.

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
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
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
    CategoryLine,
    MonthComparison,
    MonthlyReport,
    ReportAnomaly,
    ReportCompany,
)
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


__all__ = [
    "TREND_MONTHS",
    "UNCATEGORIZED",
    "NoFinancialData",
    "generate_monthly_report",
    "month_bounds",
    "parse_month",
    "previous_month",
]
