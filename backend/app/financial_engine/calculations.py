"""Deterministic financial aggregations (task 4.2, FR-3.2/FR-3.3).

Pure, DB-free functions so the money math is unit-testable in isolation and can
never depend on an LLM (architecture §4.1 / SRS FR-6.6 — the AI never calculates,
only explains these outputs). Each takes an iterable of `(date, amount, type)`
rows — where `amount` is the stored positive magnitude and `type` is
`"income"` or `"expense"` — and returns exact `Decimal` results quantized to
paise (2 dp).

* `compute_totals`  → total revenue vs. total expenses + net over the rows given
  (FR-3.2; caller decides the period by filtering which rows it passes in).
* `compute_monthly_cash_flow` → per-calendar-month inflow / outflow / net,
  ordered oldest→newest (FR-3.3).
* `compute_kpis` → burn rate / runway / margins / revenue growth (task 4.3).
* `monthly_history` → a continuous, gap-filled N-month performance series for
  the historical/12-month view (task 4.4, FR-3.5 / FR-4.6).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

_CENTS = Decimal("0.01")
ZERO = Decimal("0.00")

# numeric(6,2) columns (margins, growth, runway) hold at most ±9999.99. Ratios
# over tiny denominators can blow past that, so we clamp to keep the DB write
# from overflowing — an absurd 10000%+ / 10000-month figure isn't meaningful
# anyway, and the raw totals are stored alongside for anyone who wants them.
_RATIO_MAX = Decimal("9999.99")
_RATIO_MIN = Decimal("-9999.99")

# A minimal transaction row: (date, amount magnitude, "income"|"expense").
Row = tuple[dt.date, Decimal, str]


def quantize_money(value: Decimal) -> Decimal:
    """Quantize to 2 dp (paise), matching the DB's numeric(14,2)."""
    return Decimal(value).quantize(_CENTS)


# Shorthand used throughout this module; `quantize_money` is the name other
# modules (e.g. the scenario simulator) should import.
_q = quantize_money


@dataclass(frozen=True)
class Totals:
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    income_count: int
    expense_count: int


@dataclass(frozen=True)
class MonthlyCashFlow:
    month: str  # "YYYY-MM"
    inflow: Decimal
    outflow: Decimal
    net: Decimal


def compute_totals(rows: Iterable[Row]) -> Totals:
    """Sum income vs. expense across `rows` (FR-3.2). `net = income - expenses`.

    Amounts are positive magnitudes; direction comes from `type`. Rows with any
    other `type` are ignored (the DB constrains it to income/expense, so this is
    just defensive)."""
    income = ZERO
    expenses = ZERO
    income_count = 0
    expense_count = 0
    for _date, amount, txn_type in rows:
        value = Decimal(amount)
        if txn_type == "income":
            income += value
            income_count += 1
        elif txn_type == "expense":
            expenses += value
            expense_count += 1
    return Totals(
        total_income=_q(income),
        total_expenses=_q(expenses),
        net=_q(income - expenses),
        income_count=income_count,
        expense_count=expense_count,
    )


def compute_monthly_cash_flow(rows: Iterable[Row]) -> list[MonthlyCashFlow]:
    """Bucket `rows` by calendar month into inflow/outflow/net (FR-3.3).

    Only months that actually have transactions appear; gap-filling a
    continuous range is the 12-month view's job (task 4.4). Ordered
    oldest→newest by month key."""
    buckets: dict[str, list[Decimal]] = {}
    for date, amount, txn_type in rows:
        key = f"{date.year:04d}-{date.month:02d}"
        bucket = buckets.setdefault(key, [ZERO, ZERO])
        value = Decimal(amount)
        if txn_type == "income":
            bucket[0] += value
        elif txn_type == "expense":
            bucket[1] += value

    result: list[MonthlyCashFlow] = []
    for key in sorted(buckets):
        inflow, outflow = buckets[key]
        result.append(
            MonthlyCashFlow(
                month=key,
                inflow=_q(inflow),
                outflow=_q(outflow),
                net=_q(inflow - outflow),
            )
        )
    return result


# --- KPI snapshot metrics (task 4.3, FR-4.1–4.5) ---
#
# All deterministic; the AI CFO only ever reads these, never derives them
# (architecture §4.1 / SRS FR-6.6). Definitions locked in with the user:
#   * burn_rate          = (expenses − revenue) / months in period  (positive = burning)
#   * runway_months      = cash_on_hand / burn_rate, where cash_on_hand is the
#                          cumulative net cash flow to date (opening cash ₹0);
#                          None when not burning (burn ≤ 0) or out of cash (≤ 0).
#   * gross/operating    = (revenue − all expenses) / revenue × 100. COGS is out
#     margin_pct           of MVP scope (SRS §7), so the two are the same figure;
#                          both columns are stored for schema/report stability.
#                          None when revenue is 0 (undefined).
#   * revenue_growth_pct = (revenue − prev_revenue) / prev_revenue × 100 vs. the
#                          immediately preceding equal-length window; None when
#                          there's no prior revenue to compare against.


@dataclass(frozen=True)
class KpiValues:
    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    burn_rate: Decimal
    runway_months: Decimal | None
    gross_margin_pct: Decimal | None
    operating_margin_pct: Decimal | None
    revenue_growth_pct: Decimal | None


def months_in_period(period_start: dt.date, period_end: dt.date) -> int:
    """Inclusive count of calendar months a period spans (min 1). Jan→Jan = 1,
    Jan→Feb = 2. Used as the denominator for the monthly burn rate."""
    months = (
        (period_end.year - period_start.year) * 12
        + (period_end.month - period_start.month)
        + 1
    )
    return max(months, 1)


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Clamped, 2-dp ratio for the numeric(6,2) KPI columns."""
    value = (numerator / denominator).quantize(_CENTS, rounding=ROUND_HALF_UP)
    if value > _RATIO_MAX:
        return _RATIO_MAX
    if value < _RATIO_MIN:
        return _RATIO_MIN
    return value


def compute_kpis(
    *,
    total_revenue: Decimal,
    total_expenses: Decimal,
    num_months: int,
    cash_on_hand: Decimal,
    prev_revenue: Decimal | None,
) -> KpiValues:
    """Derive the stored KPI set from already-aggregated inputs (FR-4.1–4.5).

    Inputs are the period's revenue/expense totals, the number of months the
    period spans, the cumulative cash-on-hand as of the period end, and the
    prior equal-length window's revenue (or None if there isn't one). Pure — the
    caller does the DB aggregation."""
    revenue = Decimal(total_revenue)
    expenses = Decimal(total_expenses)
    net = revenue - expenses
    months = max(int(num_months), 1)

    burn = (expenses - revenue) / Decimal(months)

    runway: Decimal | None
    if burn > 0 and cash_on_hand > 0:
        runway = _ratio(Decimal(cash_on_hand), burn)
    else:
        # Not burning (profitable/break-even) or no cash left — runway is N/A.
        runway = None

    margin = _ratio(net * 100, revenue) if revenue > 0 else None

    growth: Decimal | None
    if prev_revenue is not None and prev_revenue > 0:
        growth = _ratio((revenue - prev_revenue) * 100, Decimal(prev_revenue))
    else:
        growth = None

    return KpiValues(
        total_revenue=_q(revenue),
        total_expenses=_q(expenses),
        net_cash_flow=_q(net),
        burn_rate=_q(burn),
        runway_months=runway,
        gross_margin_pct=margin,
        operating_margin_pct=margin,
        revenue_growth_pct=growth,
    )


# --- Historical performance / 12-month view (task 4.4, FR-3.5 / FR-4.6) ---
#
# Unlike compute_monthly_cash_flow (which only emits months that have data), the
# history view emits a *continuous* run of months — gaps are filled with zeros —
# so the dashboard can plot an unbroken trend line and "the last 12 months"
# always means twelve rows. Each month carries a profitability figure
# (margin_pct) matching the KPI definition (net / revenue × 100).


@dataclass(frozen=True)
class MonthlyPerformance:
    month: str  # "YYYY-MM"
    revenue: Decimal
    expenses: Decimal
    net_cash_flow: Decimal
    margin_pct: Decimal | None  # None when revenue is 0 (undefined)


def month_range(
    end_year: int, end_month: int, count: int
) -> list[tuple[int, int]]:
    """The `count` consecutive `(year, month)` pairs ending at
    `(end_year, end_month)`, oldest first. Handles year rollover."""
    months: list[tuple[int, int]] = []
    year, month = end_year, end_month
    for _ in range(max(count, 1)):
        months.append((year, month))
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    return list(reversed(months))


def monthly_history(
    rows: Iterable[Row],
    end_year: int,
    end_month: int,
    num_months: int = 12,
) -> list[MonthlyPerformance]:
    """A continuous `num_months`-long monthly performance series ending at
    `(end_year, end_month)`, oldest first (FR-3.5). Months without transactions
    appear as zero rows so the trend is unbroken."""
    by_month = {m.month: m for m in compute_monthly_cash_flow(rows)}

    series: list[MonthlyPerformance] = []
    for year, month in month_range(end_year, end_month, num_months):
        key = f"{year:04d}-{month:02d}"
        cf = by_month.get(key)
        revenue = cf.inflow if cf else ZERO
        expenses = cf.outflow if cf else ZERO
        net = cf.net if cf else ZERO
        margin = _ratio(net * 100, revenue) if revenue > 0 else None
        series.append(
            MonthlyPerformance(
                month=key,
                revenue=_q(revenue),
                expenses=_q(expenses),
                net_cash_flow=_q(net),
                margin_pct=margin,
            )
        )
    return series
