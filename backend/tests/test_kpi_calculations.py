"""Unit tests for deterministic KPI metrics (task 4.3, FR-4.1–4.5) — pure
functions, no DB. Definitions: burn = (expenses−revenue)/months; runway =
cash/burn (None if not burning or no cash); gross == operating margin =
(revenue−expenses)/revenue×100 (None if revenue 0); growth vs prior revenue
(None if no prior)."""

import datetime as dt
from decimal import Decimal

from app.financial_engine.calculations import (
    compute_kpis,
    months_in_period,
)


def test_months_in_period():
    d = dt.date.fromisoformat
    assert months_in_period(d("2026-01-01"), d("2026-01-31")) == 1
    assert months_in_period(d("2026-01-01"), d("2026-02-28")) == 2
    assert months_in_period(d("2026-01-01"), d("2026-12-31")) == 12
    assert months_in_period(d("2026-06-15"), d("2026-06-20")) == 1  # min 1


def test_burning_company_has_positive_burn_and_runway():
    # 3-month period: revenue 30k, expenses 60k → net −30k, burn 10k/mo.
    kpis = compute_kpis(
        total_revenue=Decimal("30000"),
        total_expenses=Decimal("60000"),
        num_months=3,
        cash_on_hand=Decimal("50000"),
        prev_revenue=Decimal("20000"),
    )
    assert kpis.net_cash_flow == Decimal("-30000.00")
    assert kpis.burn_rate == Decimal("10000.00")  # (60k−30k)/3
    assert kpis.runway_months == Decimal("5.00")  # 50k / 10k
    # Margin: (30k−60k)/30k×100 = −100%
    assert kpis.gross_margin_pct == Decimal("-100.00")
    assert kpis.operating_margin_pct == Decimal("-100.00")
    # Growth: (30k−20k)/20k×100 = 50%
    assert kpis.revenue_growth_pct == Decimal("50.00")


def test_profitable_company_has_no_runway():
    kpis = compute_kpis(
        total_revenue=Decimal("100000"),
        total_expenses=Decimal("60000"),
        num_months=1,
        cash_on_hand=Decimal("200000"),
        prev_revenue=Decimal("80000"),
    )
    assert kpis.net_cash_flow == Decimal("40000.00")
    assert kpis.burn_rate == Decimal("-40000.00")  # negative → not burning
    assert kpis.runway_months is None  # burn ≤ 0 → N/A
    assert kpis.gross_margin_pct == Decimal("40.00")  # 40k/100k
    assert kpis.revenue_growth_pct == Decimal("25.00")  # (100−80)/80


def test_no_cash_means_no_runway_even_when_burning():
    kpis = compute_kpis(
        total_revenue=Decimal("0"),
        total_expenses=Decimal("5000"),
        num_months=1,
        cash_on_hand=Decimal("-2000"),  # cumulatively underwater
        prev_revenue=Decimal("1000"),
    )
    assert kpis.burn_rate == Decimal("5000.00")
    assert kpis.runway_months is None  # cash ≤ 0 → N/A


def test_zero_revenue_margin_is_none():
    kpis = compute_kpis(
        total_revenue=Decimal("0"),
        total_expenses=Decimal("3000"),
        num_months=1,
        cash_on_hand=Decimal("0"),
        prev_revenue=Decimal("0"),
    )
    assert kpis.gross_margin_pct is None
    assert kpis.operating_margin_pct is None


def test_no_prior_revenue_growth_is_none():
    kpis = compute_kpis(
        total_revenue=Decimal("5000"),
        total_expenses=Decimal("1000"),
        num_months=1,
        cash_on_hand=Decimal("4000"),
        prev_revenue=Decimal("0"),  # no baseline
    )
    assert kpis.revenue_growth_pct is None


def test_gross_and_operating_margin_are_identical():
    # COGS out of scope → the two must always match (schema/report stability).
    kpis = compute_kpis(
        total_revenue=Decimal("12345.67"),
        total_expenses=Decimal("6789.01"),
        num_months=2,
        cash_on_hand=Decimal("1000"),
        prev_revenue=Decimal("10000"),
    )
    assert kpis.gross_margin_pct == kpis.operating_margin_pct


def test_extreme_ratios_are_clamped():
    # Tiny revenue, huge loss → margin would be far beyond numeric(6,2).
    kpis = compute_kpis(
        total_revenue=Decimal("1"),
        total_expenses=Decimal("1000000"),
        num_months=1,
        cash_on_hand=Decimal("0"),
        prev_revenue=Decimal("0.001"),  # (1−0.001)/0.001×100 ≈ 99900% → clamps
    )
    assert kpis.gross_margin_pct == Decimal("-9999.99")  # clamped floor
    assert kpis.revenue_growth_pct == Decimal("9999.99")  # clamped ceiling
