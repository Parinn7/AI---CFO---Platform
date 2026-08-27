"""Deterministic scenario simulation (task 6.2, FR-5.2).

Pure, DB-free functions, exactly like `financial_engine.calculations` — the
scenario math is ordinary Python arithmetic and an LLM is never involved
(architecture §4.1 / SRS FR-6.6). This module only *adjusts the totals*; the
KPIs themselves are then derived by reusing `compute_kpis`, so a simulated
burn rate / runway / margin / growth is produced by the same code path as a
real one and the before/after comparison is apples-to-apples (FR-5.3).

The four levers are the ones FR-5.1 names, with the input contract already
fixed by `frontend/lib/scenarios.ts`:

* `new_hires` × `avg_salary_per_hire` → added to expenses
* `marketing_change_pct` → scales the period's actual Marketing spend
* `pricing_change_pct` → scales revenue (volume assumed constant)
* `revenue_change_pct` → scales revenue (everything other than price)

Modelling decisions locked in here (task 6.2), each chosen so that before and
after are directly comparable:

1. **A scenario restates the period.** The assumptions are applied as if they
   had held for the whole `[period_start, period_end]` window, so hiring costs
   `new_hires × salary × months_in_period`. Both sides of the comparison then
   share one period and one set of KPI definitions — a forward projection would
   need its own, and FR-5.3 asks for a comparison, not a forecast.
2. **Pricing and revenue compose multiplicatively**, not additively:
   `revenue' = revenue × (1 + pricing%) × (1 + revenue%)`. Revenue is price ×
   volume, and the pricing lever explicitly holds volume constant, which makes
   the revenue lever the volume/other lever. Raising prices 10% *and* winning
   20% more business is 1.10 × 1.20 = 1.32×, not 1.30×.
3. **Only categorised Marketing spend moves.** The marketing lever scales what
   the period actually recorded against the Marketing category; spend that was
   never categorised can't be identified, so it stays put. The applied figures
   are echoed back so the user can see the base the percentage was applied to.

Cash-on-hand and prior-period revenue are the caller's job (see
`scenarios.service`), because they depend on transactions outside the period.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.financial_engine.calculations import ZERO, KpiValues, quantize_money as _q

# Percentages are expressed as whole percents (50 = +50%), matching the UI.
_HUNDRED = Decimal("100")


@dataclass(frozen=True)
class Assumptions:
    """The scenario levers. Keys mirror `frontend/lib/scenarios.ts` and, from
    6.4, the `scenarios.assumptions` jsonb column (schema §7). All default to
    "no change", so an all-zero scenario is a valid no-op that simply returns
    the baseline on both sides."""

    new_hires: int = 0
    avg_salary_per_hire: Decimal = ZERO
    marketing_change_pct: Decimal = ZERO
    pricing_change_pct: Decimal = ZERO
    revenue_change_pct: Decimal = ZERO


@dataclass(frozen=True)
class AppliedChanges:
    """What the levers actually did, in rupees — echoed back so the comparison
    can explain itself instead of just showing a different number.

    `marketing_baseline` is the categorised Marketing spend the percentage was
    applied to; `revenue_multiplier` is the combined pricing × revenue factor.
    """

    num_months: int
    added_payroll: Decimal
    marketing_baseline: Decimal
    marketing_change: Decimal
    revenue_multiplier: Decimal
    revenue_change: Decimal


@dataclass(frozen=True)
class AdjustedTotals:
    total_revenue: Decimal
    total_expenses: Decimal
    applied: AppliedChanges


def _factor(pct: Decimal) -> Decimal:
    """A whole-percent change → a multiplier. -100% → 0 (wiped out). Inputs are
    range-checked at the schema boundary, so this never goes negative."""
    return Decimal(1) + (Decimal(pct) / _HUNDRED)


def apply_assumptions(
    *,
    total_revenue: Decimal,
    total_expenses: Decimal,
    marketing_expenses: Decimal,
    num_months: int,
    assumptions: Assumptions,
) -> AdjustedTotals:
    """Adjust a period's revenue/expense totals under the scenario.

    `marketing_expenses` is the period's categorised Marketing spend (a subset
    of `total_expenses`). `num_months` is how many months the period spans, used
    to turn a monthly salary into a period cost. Pure — the caller aggregates.
    """
    revenue = Decimal(total_revenue)
    expenses = Decimal(total_expenses)
    marketing = Decimal(marketing_expenses)
    months = max(int(num_months), 1)

    # Hiring: a monthly cost per head, sustained across the whole period.
    added_payroll = (
        Decimal(assumptions.new_hires) * Decimal(assumptions.avg_salary_per_hire) * months
    )

    # Marketing: scales only what was actually booked to Marketing.
    marketing_change = marketing * (Decimal(assumptions.marketing_change_pct) / _HUNDRED)

    # Revenue: pricing and volume/other compose multiplicatively (see module docstring).
    revenue_multiplier = _factor(assumptions.pricing_change_pct) * _factor(
        assumptions.revenue_change_pct
    )
    new_revenue = revenue * revenue_multiplier
    revenue_change = new_revenue - revenue

    return AdjustedTotals(
        total_revenue=_q(new_revenue),
        total_expenses=_q(expenses + added_payroll + marketing_change),
        applied=AppliedChanges(
            num_months=months,
            added_payroll=_q(added_payroll),
            marketing_baseline=_q(marketing),
            marketing_change=_q(marketing_change),
            # 4 dp: a multiplier is a ratio, not money — quantizing it to paise
            # would throw away precision on small percentage changes.
            revenue_multiplier=Decimal(revenue_multiplier).quantize(Decimal("0.0001")),
            revenue_change=_q(revenue_change),
        ),
    )


@dataclass(frozen=True)
class KpiDeltas:
    """scenario − baseline, per metric. A delta is None whenever either side is
    None: if runway is undefined on one side (not burning cash, or out of cash),
    the difference is genuinely not a number rather than zero."""

    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    burn_rate: Decimal
    runway_months: Decimal | None
    gross_margin_pct: Decimal | None
    operating_margin_pct: Decimal | None
    revenue_growth_pct: Decimal | None


def _delta(scenario: Decimal | None, baseline: Decimal | None) -> Decimal | None:
    if scenario is None or baseline is None:
        return None
    return _q(Decimal(scenario) - Decimal(baseline))


def compute_deltas(baseline: KpiValues, scenario: KpiValues) -> KpiDeltas:
    """The before/after difference for every KPI (FR-5.3)."""
    return KpiDeltas(
        total_revenue=_q(scenario.total_revenue - baseline.total_revenue),
        total_expenses=_q(scenario.total_expenses - baseline.total_expenses),
        net_cash_flow=_q(scenario.net_cash_flow - baseline.net_cash_flow),
        burn_rate=_q(scenario.burn_rate - baseline.burn_rate),
        runway_months=_delta(scenario.runway_months, baseline.runway_months),
        gross_margin_pct=_delta(scenario.gross_margin_pct, baseline.gross_margin_pct),
        operating_margin_pct=_delta(
            scenario.operating_margin_pct, baseline.operating_margin_pct
        ),
        revenue_growth_pct=_delta(
            scenario.revenue_growth_pct, baseline.revenue_growth_pct
        ),
    )
