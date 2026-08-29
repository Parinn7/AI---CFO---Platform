"""Scenario Simulator service (task 6.2, FR-5.2).

DB-backed orchestration around the pure `scenarios.simulation` helpers. It
**reuses the Financial Engine** rather than reimplementing any of it: the
period/cumulative/prior-window aggregation comes from
`financial_engine.service.company_totals`, and both the baseline *and* the
scenario KPIs are derived by `financial_engine.calculations.compute_kpis`. That
reuse is the point of the task — a simulated runway is produced by exactly the
code that produces a real one, so the before/after comparison can't drift.

Running a scenario is stateless by design (architecture §5.2) —
`simulate_scenario` writes nothing. Task 6.4 adds the *explicit* save on top:
`save_scenario` re-runs the simulation server-side and persists the result to
`scenarios` (schema §7), and the list/get/delete helpers below let a user
revisit or discard what they saved (FR-5.4).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.financial_engine.calculations import (
    KpiValues,
    compute_kpis,
    months_in_period,
    quantize_money,
)
from app.financial_engine.models import KpiSnapshot
from app.financial_engine.service import (
    company_totals,
    generate_kpi_snapshot,
    previous_window,
)
from app.scenarios.models import Scenario
from app.scenarios.schemas import (
    AppliedChangesRead,
    ScenarioAssumptionsIn,
    ScenarioDeltas,
    ScenarioKpis,
    ScenarioSimulationRead,
)
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


# --- Saving and revisiting scenarios (task 6.4, FR-5.4) ---


def simulation_payload(
    company_id: uuid.UUID,
    assumptions: Assumptions,
    result: ScenarioSimulation,
) -> ScenarioSimulationRead:
    """Shape a simulation into the API/storage payload.

    Used by both `POST /scenarios/simulate` and `save_scenario`, so a stored
    `scenarios.result` is the *same* document the simulate endpoint returns —
    which is what lets one frontend component render a fresh run and a saved one
    without knowing which it has.
    """
    return ScenarioSimulationRead(
        company_id=company_id,
        period_start=result.period_start,
        period_end=result.period_end,
        num_months=result.num_months,
        assumptions=ScenarioAssumptionsIn(**vars(assumptions)),
        baseline=ScenarioKpis(**vars(result.baseline)),
        scenario=ScenarioKpis(**vars(result.scenario)),
        deltas=ScenarioDeltas(**vars(result.deltas)),
        applied=AppliedChangesRead(**vars(result.applied)),
    )


# The KPI columns a snapshot and a computed baseline must agree on to be
# considered the same measurement.
_KPI_FIELDS = (
    "total_revenue",
    "total_expenses",
    "net_cash_flow",
    "burn_rate",
    "runway_months",
    "gross_margin_pct",
    "operating_margin_pct",
    "revenue_growth_pct",
)


def _same_kpis(snapshot: KpiSnapshot, kpis: KpiValues) -> bool:
    """Whether a stored snapshot still states exactly what we just computed.

    Compared at money precision (2 dp, the column precision) so a round-trip
    through the DB doesn't count as a difference. A None on one side and a
    number on the other is a difference — an undefined runway is not a runway.
    """
    for field in _KPI_FIELDS:
        stored = getattr(snapshot, field)
        fresh = getattr(kpis, field)
        if (stored is None) != (fresh is None):
            return False
        if stored is not None and quantize_money(Decimal(str(stored))) != (
            quantize_money(Decimal(str(fresh)))
        ):
            return False
    return True


async def _baseline_snapshot(
    db: AsyncSession,
    company_id: uuid.UUID,
    period_start: dt.date,
    period_end: dt.date,
    baseline: KpiValues,
) -> KpiSnapshot:
    """The `kpi_snapshots` row a saved scenario points at (schema §7).

    Reuses the newest stored snapshot for the same company + period, but **only
    if it still agrees with the baseline we just computed**. A stale snapshot
    (data was added since it was generated) would make
    `baseline_kpi_snapshot_id` point at figures the saved comparison never used,
    so in that case a fresh one is generated instead. Either way the row the
    scenario references and the `result.baseline` block state the same numbers.
    """
    existing = (
        await db.execute(
            select(KpiSnapshot)
            .where(
                KpiSnapshot.company_id == company_id,
                KpiSnapshot.period_start == period_start,
                KpiSnapshot.period_end == period_end,
            )
            .order_by(KpiSnapshot.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()

    if existing is not None and _same_kpis(existing, baseline):
        return existing
    return await generate_kpi_snapshot(db, company_id, period_start, period_end)


async def save_scenario(
    db: AsyncSession,
    company_id: uuid.UUID,
    name: str,
    period_start: dt.date,
    period_end: dt.date,
    assumptions: Assumptions,
) -> Scenario:
    """Run a scenario and persist it so it can be revisited later (FR-5.4).

    The simulation is re-run server-side from the submitted levers rather than
    trusting a result the client sends up, so a stored `result` is always
    deterministic engine output (architecture §4.1). What's stored is a snapshot
    of the answer *at save time* — revisiting replays it verbatim rather than
    recomputing, so a saved scenario doesn't quietly change meaning when the
    company records new transactions.
    """
    result = await simulate_scenario(
        db, company_id, period_start, period_end, assumptions
    )
    snapshot = await _baseline_snapshot(
        db, company_id, period_start, period_end, result.baseline
    )
    payload = simulation_payload(company_id, assumptions, result)

    scenario = Scenario(
        company_id=company_id,
        name=name,
        # mode="json" so Decimals/dates land as strings, matching exactly what
        # the simulate endpoint serialises over the wire.
        assumptions=payload.assumptions.model_dump(mode="json"),
        baseline_kpi_snapshot_id=snapshot.id,
        result=payload.model_dump(mode="json"),
    )
    db.add(scenario)
    await db.commit()
    await db.refresh(scenario)
    return scenario


async def list_scenarios(
    db: AsyncSession, company_id: uuid.UUID
) -> list[Scenario]:
    """A company's saved scenarios, newest first."""
    result = await db.execute(
        select(Scenario)
        .where(Scenario.company_id == company_id)
        .order_by(Scenario.created_at.desc(), Scenario.name)
    )
    return list(result.scalars().all())


async def get_scenario_for_user(
    db: AsyncSession, scenario_id: uuid.UUID, owner_id: uuid.UUID
) -> Scenario | None:
    """A saved scenario, only if it belongs to a company the user owns (NFR-3)."""
    result = await db.execute(
        select(Scenario)
        .join(Company, Scenario.company_id == Company.id)
        .where(Scenario.id == scenario_id, Company.owner_user_id == owner_id)
    )
    return result.scalar_one_or_none()


async def delete_scenario(db: AsyncSession, scenario: Scenario) -> None:
    """Remove a saved scenario. Nothing else references it, and it holds no
    financial record of its own — the transactions and snapshots it was derived
    from are untouched."""
    await db.delete(scenario)
    await db.commit()
