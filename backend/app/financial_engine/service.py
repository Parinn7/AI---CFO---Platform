"""Financial engine service (Phase 4). DB-backed operations that use the
deterministic engine helpers — no LLM (architecture §4.1).

`auto_categorize_company` fills in `category_id` for a company's uncategorized
transactions using the rule-based `guess_category`. It's applied on demand (an
endpoint/button) and is also reused inline during upload for rows that arrive
without a category.
"""

from __future__ import annotations

import calendar
import datetime as dt
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.financial_engine.calculations import (
    MonthlyCashFlow,
    MonthlyPerformance,
    Totals,
    compute_kpis,
    compute_monthly_cash_flow,
    compute_totals,
    month_range,
    monthly_history,
    months_in_period,
)
from app.financial_engine.anomaly import ExpenseTxn, detect_expense_anomalies
from app.financial_engine.categorization import guess_category
from app.financial_engine.models import KpiSnapshot
from app.transactions.models import Transaction
from app.transactions.service import list_categories


async def auto_categorize_company(
    db: AsyncSession, company_id: uuid.UUID
) -> tuple[int, int]:
    """Assign categories to the company's uncategorized transactions.

    Returns `(categorized, uncategorized_remaining)`. Only rows the rules can
    confidently match are touched; the rest stay uncategorized.
    """
    result = await db.execute(
        select(Transaction).where(
            Transaction.company_id == company_id,
            Transaction.category_id.is_(None),
        )
    )
    transactions = list(result.scalars().all())

    by_name = {c.name.lower(): c for c in await list_categories(db, company_id)}

    categorized = 0
    for txn in transactions:
        guessed = guess_category(txn.description, txn.type)
        if guessed is None:
            continue
        category = by_name.get(guessed.lower())
        if category is not None:
            txn.category_id = category.id
            categorized += 1

    if categorized:
        await db.commit()

    return categorized, len(transactions) - categorized


# --- Revenue/expense totals + cash flow (task 4.2, FR-3.2/FR-3.3) ---


async def _load_rows(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None,
    end_date: dt.date | None,
) -> list[tuple[dt.date, object, str]]:
    """Load `(date, amount, type)` for a company's transactions, optionally
    bounded by an inclusive date range. Selecting only the three columns the
    math needs keeps the aggregation cheap and source-agnostic — upload and
    manual entries are summed identically (FR-2.6)."""
    stmt = select(
        Transaction.date, Transaction.amount, Transaction.type
    ).where(Transaction.company_id == company_id)
    if start_date is not None:
        stmt = stmt.where(Transaction.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.date <= end_date)
    result = await db.execute(stmt)
    return [tuple(row) for row in result.all()]


async def company_totals(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> Totals:
    """Total revenue vs. expenses for a company over an optional period
    (FR-3.2). Deterministic — no LLM."""
    rows = await _load_rows(db, company_id, start_date, end_date)
    return compute_totals(rows)


async def company_cash_flow(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[MonthlyCashFlow]:
    """Per-month inflow/outflow/net for a company over an optional period
    (FR-3.3). Deterministic — no LLM."""
    rows = await _load_rows(db, company_id, start_date, end_date)
    return compute_monthly_cash_flow(rows)


# --- KPI snapshots (task 4.3, FR-4.1–4.5) ---


def _previous_window(
    period_start: dt.date, period_end: dt.date
) -> tuple[dt.date, dt.date]:
    """The equal-length window immediately preceding [period_start, period_end],
    used as the revenue-growth baseline. A 31-day January window → the 31 days
    ending the day before it (2 Dec–31 Dec... i.e. Dec 1–Dec 31 for a full Jan)."""
    length = (period_end - period_start).days + 1
    prev_end = period_start - dt.timedelta(days=1)
    prev_start = prev_end - dt.timedelta(days=length - 1)
    return prev_start, prev_end


async def generate_kpi_snapshot(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
) -> KpiSnapshot:
    """Compute and persist a KPI snapshot for a company over the given period
    (FR-4.1–4.5). All figures are deterministic (architecture §4.1); this is the
    only writer of `kpi_snapshots`, which the AI CFO later reads from.

    Cash-on-hand for runway is the cumulative net cash flow through `period_end`
    (opening cash ₹0). Revenue growth compares against the immediately preceding
    equal-length window."""
    period_totals = compute_totals(
        await _load_rows(db, company_id, period_start, period_end)
    )

    # Cumulative cash position as of period_end (all transactions up to then).
    cumulative = compute_totals(await _load_rows(db, company_id, None, period_end))
    cash_on_hand = cumulative.total_income - cumulative.total_expenses

    prev_start, prev_end = _previous_window(period_start, period_end)
    prev_totals = compute_totals(
        await _load_rows(db, company_id, prev_start, prev_end)
    )

    kpis = compute_kpis(
        total_revenue=period_totals.total_income,
        total_expenses=period_totals.total_expenses,
        num_months=months_in_period(period_start, period_end),
        cash_on_hand=cash_on_hand,
        prev_revenue=prev_totals.total_income,
    )

    snapshot = KpiSnapshot(
        company_id=company_id,
        period_start=period_start,
        period_end=period_end,
        total_revenue=kpis.total_revenue,
        total_expenses=kpis.total_expenses,
        net_cash_flow=kpis.net_cash_flow,
        burn_rate=kpis.burn_rate,
        runway_months=kpis.runway_months,
        gross_margin_pct=kpis.gross_margin_pct,
        operating_margin_pct=kpis.operating_margin_pct,
        revenue_growth_pct=kpis.revenue_growth_pct,
    )
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)
    return snapshot


async def list_kpi_snapshots(
    db: AsyncSession, company_id: uuid.UUID
) -> list[KpiSnapshot]:
    """A company's stored KPI snapshots, most recent period first."""
    result = await db.execute(
        select(KpiSnapshot)
        .where(KpiSnapshot.company_id == company_id)
        .order_by(KpiSnapshot.period_end.desc(), KpiSnapshot.created_at.desc())
    )
    return list(result.scalars().all())


# --- Historical performance / 12-month view (task 4.4, FR-3.5 / FR-4.6) ---


async def _latest_transaction_month(
    db: AsyncSession, company_id: uuid.UUID
) -> tuple[int, int] | None:
    """The (year, month) of the company's most recent transaction, or None."""
    result = await db.execute(
        select(func.max(Transaction.date)).where(
            Transaction.company_id == company_id
        )
    )
    latest = result.scalar_one_or_none()
    return (latest.year, latest.month) if latest is not None else None


async def company_history(
    db: AsyncSession,
    company_id: uuid.UUID,
    num_months: int = 12,
    end_month: tuple[int, int] | None = None,
) -> tuple[list[MonthlyPerformance], tuple[int, int]]:
    """A continuous `num_months`-long monthly performance series (FR-3.5),
    oldest first, with empty months zero-filled. Returns `(series, anchor)`.

    The anchor (last month in the series) defaults to the month of the company's
    most recent transaction — i.e. the last 12 months *of available data* — and
    falls back to the current month when there are no transactions yet. Only the
    window's transactions are loaded, then bucketed deterministically."""
    if end_month is None:
        today = dt.date.today()
        end_month = await _latest_transaction_month(db, company_id) or (
            today.year,
            today.month,
        )
    end_year, end_mo = end_month

    window = month_range(end_year, end_mo, num_months)
    start_year, start_mo = window[0]
    window_start = dt.date(start_year, start_mo, 1)
    last_day = calendar.monthrange(end_year, end_mo)[1]
    window_end = dt.date(end_year, end_mo, last_day)

    rows = await _load_rows(db, company_id, window_start, window_end)
    series = monthly_history(rows, end_year, end_mo, num_months)
    return series, end_month


# --- Anomaly detection (task 4.5, FR-3.6) ---


async def detect_anomalies_for_company(
    db: AsyncSession, company_id: uuid.UUID
) -> tuple[int, int]:
    """Recompute `is_flagged_anomaly` for all of a company's transactions using
    the deterministic category-month spike rule (FR-3.6). No LLM.

    Returns `(flagged, expenses_scanned)`. This is a full, idempotent recompute:
    every transaction's flag is set to its correct current value (so edits/deletes
    that change baselines, or transactions that are no longer anomalous, are
    cleared), and only expenses can end up flagged."""
    result = await db.execute(
        select(Transaction).where(Transaction.company_id == company_id)
    )
    transactions = list(result.scalars().all())

    expenses = [t for t in transactions if t.type == "expense"]
    flagged_ids = detect_expense_anomalies(
        ExpenseTxn(id=t.id, group=t.category_id, date=t.date, amount=t.amount)
        for t in expenses
    )

    changed = False
    for txn in transactions:
        should_flag = txn.id in flagged_ids
        if txn.is_flagged_anomaly != should_flag:
            txn.is_flagged_anomaly = should_flag
            changed = True

    if changed:
        await db.commit()

    return len(flagged_ids), len(expenses)
