"""Unit tests for deterministic expense-anomaly detection (task 4.5, FR-3.6)
— pure functions, no DB. Rule: an expense category's monthly spend exceeding
its trailing 3-month average by >50% flags that month's transactions; a full
trailing-3-month baseline is required."""

import datetime as dt
from decimal import Decimal

from app.financial_engine.anomaly import ExpenseTxn, detect_expense_anomalies


def _txn(tid, group, date, amount):
    return ExpenseTxn(id=tid, group=group, date=dt.date.fromisoformat(date), amount=Decimal(amount))


def test_spike_after_full_trailing_baseline_is_flagged():
    # Rent ~1000/mo for Jan–Mar, then 5000 in Apr → spike vs avg 1000.
    txns = [
        _txn("a", "rent", "2026-01-15", "1000"),
        _txn("b", "rent", "2026-02-15", "1000"),
        _txn("c", "rent", "2026-03-15", "1000"),
        _txn("d", "rent", "2026-04-15", "5000"),
    ]
    assert detect_expense_anomalies(txns) == {"d"}


def test_within_threshold_is_not_flagged():
    # Apr = 1400 vs avg 1000 → +40%, under the 50% threshold.
    txns = [
        _txn("a", "rent", "2026-01-15", "1000"),
        _txn("b", "rent", "2026-02-15", "1000"),
        _txn("c", "rent", "2026-03-15", "1000"),
        _txn("d", "rent", "2026-04-15", "1400"),
    ]
    assert detect_expense_anomalies(txns) == set()


def test_incomplete_trailing_baseline_is_not_flagged():
    # Only Feb + Mar precede the Apr spike (Jan missing) → no full 3-mo baseline.
    txns = [
        _txn("b", "rent", "2026-02-15", "1000"),
        _txn("c", "rent", "2026-03-15", "1000"),
        _txn("d", "rent", "2026-04-15", "9000"),
    ]
    assert detect_expense_anomalies(txns) == set()


def test_all_transactions_in_flagged_bucket_are_flagged():
    # Two payments make up April's spike → both flagged.
    txns = [
        _txn("a", "marketing", "2026-01-10", "2000"),
        _txn("b", "marketing", "2026-02-10", "2000"),
        _txn("c", "marketing", "2026-03-10", "2000"),
        _txn("d", "marketing", "2026-04-05", "4000"),
        _txn("e", "marketing", "2026-04-25", "4000"),  # April total 8000 vs avg 2000
    ]
    assert detect_expense_anomalies(txns) == {"d", "e"}


def test_groups_are_independent():
    # Rent is steady; marketing spikes. Only marketing flags.
    txns = [
        _txn("r1", "rent", "2026-01-01", "1000"),
        _txn("r2", "rent", "2026-02-01", "1000"),
        _txn("r3", "rent", "2026-03-01", "1000"),
        _txn("r4", "rent", "2026-04-01", "1000"),
        _txn("m1", "marketing", "2026-01-01", "500"),
        _txn("m2", "marketing", "2026-02-01", "500"),
        _txn("m3", "marketing", "2026-03-01", "500"),
        _txn("m4", "marketing", "2026-04-01", "3000"),
    ]
    assert detect_expense_anomalies(txns) == {"m4"}


def test_uncategorized_group_none_is_handled():
    txns = [
        _txn("a", None, "2026-01-15", "1000"),
        _txn("b", None, "2026-02-15", "1000"),
        _txn("c", None, "2026-03-15", "1000"),
        _txn("d", None, "2026-04-15", "5000"),
    ]
    assert detect_expense_anomalies(txns) == {"d"}


def test_year_boundary_trailing_months():
    # Baseline Oct–Dec 2025, spike Jan 2026.
    txns = [
        _txn("a", "ops", "2025-10-10", "1000"),
        _txn("b", "ops", "2025-11-10", "1000"),
        _txn("c", "ops", "2025-12-10", "1000"),
        _txn("d", "ops", "2026-01-10", "5000"),
    ]
    assert detect_expense_anomalies(txns) == {"d"}


def test_empty_input():
    assert detect_expense_anomalies([]) == set()
