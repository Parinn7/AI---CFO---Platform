"""Unit tests for deterministic financial aggregations (task 4.2, FR-3.2/3.3)
— pure functions, no DB needed."""

import datetime as dt
from decimal import Decimal

from app.financial_engine.calculations import (
    compute_monthly_cash_flow,
    compute_totals,
)


def _row(date: str, amount: str, txn_type: str):
    return (dt.date.fromisoformat(date), Decimal(amount), txn_type)


def test_totals_sum_income_and_expenses_and_net():
    rows = [
        _row("2026-01-05", "5000", "income"),
        _row("2026-01-10", "7000.50", "income"),
        _row("2026-01-12", "2000.25", "expense"),
        _row("2026-02-01", "1000", "expense"),
    ]
    totals = compute_totals(rows)
    assert totals.total_income == Decimal("12000.50")
    assert totals.total_expenses == Decimal("3000.25")
    assert totals.net == Decimal("9000.25")
    assert totals.income_count == 2
    assert totals.expense_count == 2


def test_totals_empty_is_zero():
    totals = compute_totals([])
    assert totals.total_income == Decimal("0.00")
    assert totals.total_expenses == Decimal("0.00")
    assert totals.net == Decimal("0.00")
    assert totals.income_count == 0
    assert totals.expense_count == 0


def test_totals_net_can_be_negative():
    rows = [_row("2026-03-01", "500", "income"), _row("2026-03-02", "1500", "expense")]
    assert compute_totals(rows).net == Decimal("-1000.00")


def test_totals_are_quantized_to_two_places():
    # Two rows that each round cleanly but whose raw sum needs quantizing.
    rows = [_row("2026-01-01", "0.1", "income"), _row("2026-01-01", "0.2", "income")]
    totals = compute_totals(rows)
    assert totals.total_income == Decimal("0.30")
    assert str(totals.total_income) == "0.30"


def test_monthly_cash_flow_buckets_by_calendar_month_ordered():
    rows = [
        _row("2026-02-15", "3000", "income"),
        _row("2026-01-10", "5000", "income"),
        _row("2026-01-20", "2000", "expense"),
        _row("2026-02-25", "1000", "expense"),
        _row("2026-01-31", "500", "income"),
    ]
    months = compute_monthly_cash_flow(rows)
    assert [m.month for m in months] == ["2026-01", "2026-02"]  # oldest first

    jan, feb = months
    assert jan.inflow == Decimal("5500.00")  # 5000 + 500
    assert jan.outflow == Decimal("2000.00")
    assert jan.net == Decimal("3500.00")
    assert feb.inflow == Decimal("3000.00")
    assert feb.outflow == Decimal("1000.00")
    assert feb.net == Decimal("2000.00")


def test_monthly_cash_flow_only_months_with_data():
    # Jan and Mar have data, Feb is skipped entirely (gap-filling is task 4.4).
    rows = [
        _row("2026-01-05", "1000", "income"),
        _row("2026-03-05", "2000", "income"),
    ]
    months = compute_monthly_cash_flow(rows)
    assert [m.month for m in months] == ["2026-01", "2026-03"]


def test_monthly_cash_flow_empty():
    assert compute_monthly_cash_flow([]) == []
