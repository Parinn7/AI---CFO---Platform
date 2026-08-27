"""Unit tests for the pure scenario math (task 6.2, FR-5.2).

DB-free, mirroring `test_kpi_calculations.py` — these lock in the modelling
decisions documented in `app/scenarios/simulation.py`.
"""

from decimal import Decimal

from app.financial_engine.calculations import compute_kpis
from app.scenarios.simulation import (
    Assumptions,
    apply_assumptions,
    compute_deltas,
)


def _apply(**kwargs):
    base = dict(
        total_revenue=Decimal("1000000.00"),
        total_expenses=Decimal("600000.00"),
        marketing_expenses=Decimal("100000.00"),
        num_months=12,
    )
    base.update(kwargs)
    return apply_assumptions(**base)


def test_no_levers_is_a_no_op():
    """An all-zero scenario returns the baseline untouched — accepted, not an
    error, since "nothing changes" is a truthful answer."""
    result = _apply(assumptions=Assumptions())
    assert result.total_revenue == Decimal("1000000.00")
    assert result.total_expenses == Decimal("600000.00")
    assert result.applied.added_payroll == Decimal("0.00")
    assert result.applied.revenue_multiplier == Decimal("1.0000")


def test_hiring_costs_salary_times_months():
    """Hiring is a monthly cost sustained across the whole period."""
    result = _apply(
        assumptions=Assumptions(new_hires=3, avg_salary_per_hire=Decimal("80000"))
    )
    # 3 × 80,000 × 12 months = 2,880,000 added to expenses.
    assert result.applied.added_payroll == Decimal("2880000.00")
    assert result.total_expenses == Decimal("3480000.00")
    assert result.total_revenue == Decimal("1000000.00")  # untouched


def test_hiring_with_no_salary_costs_nothing():
    result = _apply(assumptions=Assumptions(new_hires=5))
    assert result.applied.added_payroll == Decimal("0.00")
    assert result.total_expenses == Decimal("600000.00")


def test_marketing_scales_only_categorised_marketing_spend():
    """+50% applies to the 100k of Marketing, not the 600k of total expenses."""
    result = _apply(assumptions=Assumptions(marketing_change_pct=Decimal("50")))
    assert result.applied.marketing_baseline == Decimal("100000.00")
    assert result.applied.marketing_change == Decimal("50000.00")
    assert result.total_expenses == Decimal("650000.00")


def test_marketing_cut_reduces_expenses():
    result = _apply(assumptions=Assumptions(marketing_change_pct=Decimal("-20")))
    assert result.applied.marketing_change == Decimal("-20000.00")
    assert result.total_expenses == Decimal("580000.00")


def test_marketing_lever_does_nothing_without_categorised_spend():
    """Uncategorised marketing can't be identified, so the lever has no base."""
    result = _apply(
        marketing_expenses=Decimal("0"),
        assumptions=Assumptions(marketing_change_pct=Decimal("100")),
    )
    assert result.applied.marketing_baseline == Decimal("0.00")
    assert result.total_expenses == Decimal("600000.00")


def test_pricing_and_revenue_compose_multiplicatively():
    """+10% price and +20% other business = 1.32x, not 1.30x — revenue is
    price x volume and the pricing lever holds volume constant."""
    result = _apply(
        assumptions=Assumptions(
            pricing_change_pct=Decimal("10"), revenue_change_pct=Decimal("20")
        )
    )
    assert result.applied.revenue_multiplier == Decimal("1.3200")
    assert result.total_revenue == Decimal("1320000.00")
    assert result.applied.revenue_change == Decimal("320000.00")


def test_revenue_can_be_wiped_out():
    """-100% is the floor the schema allows; revenue goes to zero, not negative."""
    result = _apply(assumptions=Assumptions(revenue_change_pct=Decimal("-100")))
    assert result.total_revenue == Decimal("0.00")
    assert result.applied.revenue_multiplier == Decimal("0.0000")


def test_levers_combine():
    result = _apply(
        assumptions=Assumptions(
            new_hires=2,
            avg_salary_per_hire=Decimal("50000"),
            marketing_change_pct=Decimal("50"),
            pricing_change_pct=Decimal("10"),
        )
    )
    # expenses: 600,000 + (2 × 50,000 × 12) + 50,000 = 1,850,000
    assert result.total_expenses == Decimal("1850000.00")
    assert result.total_revenue == Decimal("1100000.00")


def test_deltas_are_scenario_minus_baseline():
    baseline = compute_kpis(
        total_revenue=Decimal("1000000"),
        total_expenses=Decimal("600000"),
        num_months=12,
        cash_on_hand=Decimal("400000"),
        prev_revenue=Decimal("800000"),
    )
    scenario = compute_kpis(
        total_revenue=Decimal("1100000"),
        total_expenses=Decimal("600000"),
        num_months=12,
        cash_on_hand=Decimal("500000"),
        prev_revenue=Decimal("800000"),
    )
    deltas = compute_deltas(baseline, scenario)
    assert deltas.total_revenue == Decimal("100000.00")
    assert deltas.total_expenses == Decimal("0.00")
    assert deltas.net_cash_flow == Decimal("100000.00")
    # Both profitable → both runways undefined → the difference is not a number.
    assert baseline.runway_months is None and scenario.runway_months is None
    assert deltas.runway_months is None
    # Growth moves from +25% to +37.5%.
    assert deltas.revenue_growth_pct == Decimal("12.50")


def test_delta_is_none_when_only_one_side_is_defined():
    """A runway that exists on one side only has no meaningful difference."""
    burning = compute_kpis(
        total_revenue=Decimal("100000"),
        total_expenses=Decimal("400000"),
        num_months=12,
        cash_on_hand=Decimal("600000"),
        prev_revenue=None,
    )
    profitable = compute_kpis(
        total_revenue=Decimal("500000"),
        total_expenses=Decimal("400000"),
        num_months=12,
        cash_on_hand=Decimal("600000"),
        prev_revenue=None,
    )
    assert burning.runway_months is not None
    assert profitable.runway_months is None
    assert compute_deltas(burning, profitable).runway_months is None
