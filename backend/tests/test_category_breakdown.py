"""Unit tests for the pure category breakdown (task 8.1, FR-7.1).

DB-free, like the rest of `financial_engine.calculations` — the aggregation a
report's line items are built from, tested on its own.
"""

from decimal import Decimal

from app.financial_engine.calculations import compute_category_breakdown


def _rows(*rows):
    return [(g, Decimal(a), t) for g, a, t in rows]


def test_totals_and_counts_per_category():
    result = compute_category_breakdown(
        _rows(
            ("payroll", "60000", "expense"),
            ("payroll", "40000", "expense"),
            ("rent", "25000", "expense"),
        )
    )
    by_key = {line.group: line for line in result}
    assert by_key["payroll"].total == Decimal("100000.00")
    assert by_key["payroll"].count == 2
    assert by_key["rent"].total == Decimal("25000.00")
    assert by_key["rent"].count == 1


def test_share_is_of_own_type_not_of_everything():
    """An expense's share is of all expenses, not of every rupee that moved.

    Revenue 100k, expenses 75k+25k. Payroll is 75% of expenses; against a
    combined 200k denominator it would read 37.5%, which is not a number anyone
    would want on a report."""
    result = compute_category_breakdown(
        _rows(
            ("revenue", "100000", "income"),
            ("payroll", "75000", "expense"),
            ("rent", "25000", "expense"),
        )
    )
    by_key = {line.group: line for line in result}
    assert by_key["payroll"].share_pct == Decimal("75.00")
    assert by_key["rent"].share_pct == Decimal("25.00")
    assert by_key["revenue"].share_pct == Decimal("100.00")


def test_income_first_then_largest_expense():
    result = compute_category_breakdown(
        _rows(
            ("rent", "25000", "expense"),
            ("payroll", "75000", "expense"),
            ("revenue", "100000", "income"),
        )
    )
    assert [line.group for line in result] == ["revenue", "payroll", "rent"]


def test_uncategorized_is_its_own_line_not_dropped():
    """Silently omitting uncategorized spend would understate expenses — the
    lines have to add up to the totals printed above them."""
    result = compute_category_breakdown(
        _rows(
            ("payroll", "60000", "expense"),
            (None, "40000", "expense"),
        )
    )
    by_key = {line.group: line for line in result}
    assert None in by_key
    assert by_key[None].total == Decimal("40000.00")
    assert sum(line.total for line in result) == Decimal("100000.00")


def test_type_with_no_activity_has_no_lines():
    result = compute_category_breakdown(_rows(("payroll", "1000", "expense")))
    assert [line.type for line in result] == ["expense"]


def test_ties_keep_a_stable_order():
    """Two categories with identical totals must not swap between renders."""
    first = compute_category_breakdown(
        _rows(("alpha", "500", "expense"), ("beta", "500", "expense"))
    )
    second = compute_category_breakdown(
        _rows(("beta", "500", "expense"), ("alpha", "500", "expense"))
    )
    assert [line.group for line in first] == [line.group for line in second]
