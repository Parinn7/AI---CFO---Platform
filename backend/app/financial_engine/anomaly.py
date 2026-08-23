"""Deterministic expense-anomaly detection (task 4.5, FR-3.6).

Pure, DB-free, **no LLM** (architecture §4.1). Implements the SRS-specified rule
(§7 MVP decision): flag an expense **category whose spend in a month deviates
upward by more than a fixed threshold from its trailing 3-month average**, then
mark that month's transactions in that category as anomalies. Fixed default
thresholds, not per-company configuration (configurability is post-MVP).

Why category-month (not per-transaction size): FR-3.6 is about "unusual spikes
relative to historical average", and the SRS pins the baseline to a trailing
3-month average per expense category. A single large-but-normal payment (e.g.
quarterly rent) shouldn't flag on size alone; a category's monthly spend jumping
well above its recent norm is the real signal. The per-transaction
`is_flagged_anomaly` column is then set for every transaction in a flagged
(category, month) bucket so the dashboard can highlight them (FR-8.3).

Requiring a *full* trailing 3 months of spend before evaluating a month keeps
this honest — a brand-new category with no history is never flagged as a "spike".
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Hashable, Iterable

from app.financial_engine.calculations import month_range

# Fixed thresholds (tunable constants, not per-company config — SRS §7).
# A month's category spend must exceed its trailing-average by more than this
# fraction to count as a spike. 0.5 = 50% above the trailing 3-month average.
ANOMALY_THRESHOLD_PCT = Decimal("0.5")
# Number of preceding months averaged for the baseline, all of which must have
# spend for the current month to be evaluated.
TRAILING_MONTHS = 3

_ZERO = Decimal("0")


@dataclass(frozen=True)
class ExpenseTxn:
    """Minimal expense row for detection. `group` is the category id (or None for
    uncategorized — treated as its own group). `amount` is a positive magnitude."""

    id: Hashable
    group: Hashable
    date: dt.date
    amount: Decimal


def _previous_months(
    year: int, month: int, count: int
) -> list[tuple[int, int]]:
    """The `count` calendar months immediately *before* (year, month), any
    order (used only for lookups)."""
    # month_range(...count+1) ends at (year, month) inclusive; drop that last one.
    return month_range(year, month, count + 1)[:-1]


def detect_expense_anomalies(txns: Iterable[ExpenseTxn]) -> set[Hashable]:
    """Return the ids of expense transactions that fall in an anomalous
    (category, month) bucket — i.e. a month whose category spend exceeds its
    trailing 3-month average by more than `ANOMALY_THRESHOLD_PCT`, with a full
    trailing baseline present. Deterministic; income should not be passed in."""
    totals: dict[tuple[Hashable, tuple[int, int]], Decimal] = {}
    ids: dict[tuple[Hashable, tuple[int, int]], list[Hashable]] = {}

    for txn in txns:
        key = (txn.group, (txn.date.year, txn.date.month))
        totals[key] = totals.get(key, _ZERO) + Decimal(txn.amount)
        ids.setdefault(key, []).append(txn.id)

    flagged: set[Hashable] = set()
    multiplier = Decimal(1) + ANOMALY_THRESHOLD_PCT

    for (group, (year, month)), total in totals.items():
        trailing = [
            totals.get((group, prev), _ZERO)
            for prev in _previous_months(year, month, TRAILING_MONTHS)
        ]
        # Need a full trailing baseline (every preceding month had spend).
        if not all(value > 0 for value in trailing):
            continue
        baseline = sum(trailing, _ZERO) / Decimal(len(trailing))
        if total > baseline * multiplier:
            flagged.update(ids[(group, (year, month))])

    return flagged
