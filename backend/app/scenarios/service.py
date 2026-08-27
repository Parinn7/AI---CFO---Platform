"""Scenario Simulator service (task 6.2, FR-5.2).

DB-backed orchestration around the pure `scenarios.simulation` helpers. It
**reuses the Financial Engine** rather than reimplementing any of it: the
period/cumulative/prior-window aggregation comes from
`financial_engine.service.company_totals`, and both the baseline *and* the
scenario KPIs are derived by `financial_engine.calculations.compute_kpis`. That
reuse is the point of the task — a simulated runway is produced by exactly the
code that produces a real one, so the before/after comparison can't drift.

Stateless by design (architecture §5.2): nothing here writes. Persisting a
scenario is 6.4's job.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.financial_engine.calculations import (
    KpiValues,
    compute_kpis,
    months_in_period,
)
from app.financial_engine.service import company_totals, previous_window
from app.scenarios.simulation import (
    AppliedChanges,
    Assumptions,
    KpiDeltas,
    apply_assumptions,
    compute_deltas,
)
from app.transactions.models import Category, Transaction

# The default expense category the marketing lever acts on (see
# `transactions.categories.DEFAULT_CATEGORIES`). Matched case-insensitively so a
# company-specific "marketing" category counts too.
MARKETING_CATEGORY = "Marketing"


@dataclass(frozen=True)
class ScenarioSimulation:
    """The full before/after result (FR-5.3)."""

    period_start: dt.date
    period_end: dt.date
    num_months: int
    baseline: KpiValues
    scenario: KpiValues
    deltas: KpiDeltas
    applied: AppliedChanges


async def category_expense_total(
    db: AsyncSession,
    company_id: uuid.UUID,
    category_name: str,
    start_date: dt.date,
    end_date: dt.date,
) -> Decimal:
    """Total expense booked to a named category over an inclusive period.

    Only categorised rows can be matched, so spend the user never categorised
    is not included — which is why the caller echoes this figure back as the
    base the percentage was applied to. Source-agnostic: manual and uploaded
    transactions count identically (FR-2.6)."""
    result = await db.execute(
        select(func.coalesce(func.sum(Transaction.amount), 0))
        .join(Category, Transaction.category_id == Category.id)
        .where(
            Transaction.company_id == company_id,
            Transaction.type == "expense",
            func.lower(Category.name) == category_name.lower(),
            Transaction.date >= start_date,
            Transaction.date <= end_date,
        )
    )
    return Decimal(result.scalar_one() or 0)


async def simulate_scenario(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
    assumptions: Assumptions,
) -> ScenarioSimulation:
    """Recalculate cash flow, runway, profitability and growth under a
    hypothetical (FR-5.2), against the real figures for the same period.

    Deterministic end to end — no LLM is involved at any point (architecture
    §4.1). Writes nothing.

    Three inputs come from outside the period and are handled here rather than
    in the pure module:

    * **cash-on-hand** — cumulative net cash flow through `period_end` (opening
      cash ₹0), matching `generate_kpi_snapshot`, and deliberately **the same on
      both sides**: the scenario restates the burn rate but not the money
      actually in the bank. Runway then answers the question a founder actually
      asks — "I have this much cash; if I hire five people, how long does it
      last?" Restating cash as well is more internally consistent but reads as
      "if you'd been doing this all year you'd have run out", which collapses
      runway to N/A (out of cash) in most realistic scenarios and makes one of
      the four KPIs FR-5.2 names useless. Decision made with the user in 6.2.
    * **prior revenue** — growth is measured against the *actual* preceding
      equal-length window on both sides. A scenario doesn't rewrite history, so
      "what would growth have been" is the honest comparison.
    * **marketing spend** — the base the marketing lever scales.
    """
    period = await company_totals(db, company_id, period_start, period_end)

    # Cumulative cash position as of period_end, exactly as the KPI snapshot
    # defines it (opening cash ₹0).
    cumulative = await company_totals(db, company_id, None, period_end)
    baseline_cash = cumulative.total_income - cumulative.total_expenses

    prev_start, prev_end = previous_window(period_start, period_end)
    prev = await company_totals(db, company_id, prev_start, prev_end)

    num_months = months_in_period(period_start, period_end)

    baseline = compute_kpis(
        total_revenue=period.total_income,
        total_expenses=period.total_expenses,
        num_months=num_months,
        cash_on_hand=baseline_cash,
        prev_revenue=prev.total_income,
    )

    marketing = await category_expense_total(
        db, company_id, MARKETING_CATEGORY, period_start, period_end
    )
    adjusted = apply_assumptions(
        total_revenue=period.total_income,
        total_expenses=period.total_expenses,
        marketing_expenses=marketing,
        num_months=num_months,
        assumptions=assumptions,
    )

    scenario = compute_kpis(
        total_revenue=adjusted.total_revenue,
        total_expenses=adjusted.total_expenses,
        num_months=num_months,
        # Cash on hand is the company's *real* position — see the docstring.
        cash_on_hand=baseline_cash,
        prev_revenue=prev.total_income,
    )

    return ScenarioSimulation(
        period_start=period_start,
        period_end=period_end,
        num_months=num_months,
        baseline=baseline,
        scenario=scenario,
        deltas=compute_deltas(baseline, scenario),
        applied=adjusted.applied,
    )
