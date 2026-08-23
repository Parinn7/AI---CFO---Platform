"""Unit tests for the historical/12-month performance series (task 4.4,
FR-3.5/FR-4.6) — pure functions, no DB."""

import datetime as dt
from decimal import Decimal

from app.financial_engine.calculations import month_range, monthly_history


def _row(date: str, amount: str, txn_type: str):
    return (dt.date.fromisoformat(date), Decimal(amount), txn_type)


def test_month_range_oldest_first_with_year_rollover():
    assert month_range(2026, 2, 4) == [
        (2025, 11),
        (2025, 12),
        (2026, 1),
        (2026, 2),
    ]


def test_month_range_single_month():
    assert month_range(2026, 6, 1) == [(2026, 6)]


def test_history_is_continuous_and_zero_fills_gaps():
    # Data only in Jan and Mar; Feb must appear as a zero row.
    rows = [
        _row("2026-01-10", "5000", "income"),
        _row("2026-01-20", "2000", "expense"),
        _row("2026-03-05", "8000", "income"),
    ]
    series = monthly_history(rows, 2026, 3, num_months=3)
    assert [m.month for m in series] == ["2026-01", "2026-02", "2026-03"]

    jan, feb, mar = series
    assert jan.revenue == Decimal("5000.00")
    assert jan.expenses == Decimal("2000.00")
    assert jan.net_cash_flow == Decimal("3000.00")
    assert jan.margin_pct == Decimal("60.00")  # 3000/5000×100

    assert feb.revenue == Decimal("0.00")
    assert feb.expenses == Decimal("0.00")
    assert feb.net_cash_flow == Decimal("0.00")
    assert feb.margin_pct is None  # revenue 0 → undefined

    assert mar.revenue == Decimal("8000.00")
    assert mar.margin_pct == Decimal("100.00")  # no expenses


def test_history_always_returns_num_months_rows():
    series = monthly_history([], 2026, 8, num_months=12)
    assert len(series) == 12
    assert series[0].month == "2025-09"
    assert series[-1].month == "2026-08"
    assert all(m.revenue == Decimal("0.00") for m in series)
    assert all(m.margin_pct is None for m in series)


def test_history_ignores_data_outside_the_window():
    # A December 2025 row is outside a Jan–Mar 2026 window (num_months=3).
    rows = [
        _row("2025-12-31", "9999", "income"),
        _row("2026-02-15", "1000", "income"),
    ]
    series = monthly_history(rows, 2026, 3, num_months=3)
    assert [m.month for m in series] == ["2026-01", "2026-02", "2026-03"]
    assert sum(m.revenue for m in series) == Decimal("1000.00")
