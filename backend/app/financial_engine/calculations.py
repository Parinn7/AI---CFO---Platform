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
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable

_CENTS = Decimal("0.01")
ZERO = Decimal("0.00")

# A minimal transaction row: (date, amount magnitude, "income"|"expense").
Row = tuple[dt.date, Decimal, str]


def _q(value: Decimal) -> Decimal:
    """Quantize to 2 dp (paise), matching the DB's numeric(14,2)."""
    return Decimal(value).quantize(_CENTS)


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
