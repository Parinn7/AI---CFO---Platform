"""Pydantic schemas for the Scenario Simulator (task 6.2, FR-5.2/FR-5.3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ScenarioAssumptionsIn(BaseModel):
    """The scenario levers (FR-5.1).

    Field names and bounds deliberately mirror `frontend/lib/scenarios.ts`, so
    the form's client-side validation and this server-side check agree, and so
    the object can be persisted verbatim as `scenarios.assumptions` in 6.4
    (schema §7). Every lever defaults to "no change" — an all-zero scenario is
    accepted and simply returns identical before/after figures, which is a
    truthful answer rather than an error worth raising.
    """

    model_config = ConfigDict(extra="forbid")

    new_hires: int = Field(0, ge=0, le=500)
    avg_salary_per_hire: Decimal = Field(Decimal("0"), ge=0, le=10_000_000)
    marketing_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=1000)
    pricing_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=1000)
    revenue_change_pct: Decimal = Field(Decimal("0"), ge=-100, le=1000)


class ScenarioSimulateRequest(BaseModel):
    """Simulate a scenario over a period. Stateless — nothing is persisted
    (architecture §5.2); saving is 6.4's job."""

    company_id: uuid.UUID
    period_start: dt.date
    period_end: dt.date
    assumptions: ScenarioAssumptionsIn

    @model_validator(mode="after")
    def _ordered(self) -> "ScenarioSimulateRequest":
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end.")
        return self


class ScenarioKpis(BaseModel):
    """One side of the comparison — the same KPI set a `kpi_snapshot` holds
    (FR-4.1–4.5), computed by the same deterministic code. Runway/margins/growth
    are null in their undefined cases (not burning cash, zero revenue, no prior
    period)."""

    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    burn_rate: Decimal
    runway_months: Decimal | None
    gross_margin_pct: Decimal | None
    operating_margin_pct: Decimal | None
    revenue_growth_pct: Decimal | None


class ScenarioDeltas(BaseModel):
    """scenario − baseline per metric. Null when either side is undefined —
    e.g. a runway that doesn't exist before *or* after has no difference."""

    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    burn_rate: Decimal
    runway_months: Decimal | None
    gross_margin_pct: Decimal | None
    operating_margin_pct: Decimal | None
    revenue_growth_pct: Decimal | None


class AppliedChangesRead(BaseModel):
    """What the levers actually did, in rupees, so the comparison can explain
    itself. `marketing_baseline` is the categorised Marketing spend the
    percentage was applied to (uncategorised spend can't be identified, so it
    isn't moved); `revenue_multiplier` is the combined pricing × revenue
    factor."""

    num_months: int
    added_payroll: Decimal
    marketing_baseline: Decimal
    marketing_change: Decimal
    revenue_multiplier: Decimal
    revenue_change: Decimal


class ScenarioSimulationRead(BaseModel):
    """A full before/after comparison (FR-5.2/FR-5.3).

    `baseline` is identical to the `kpi_snapshot` for the same company+period —
    same inputs, same deterministic code — so 6.4 can store a
    `baseline_kpi_snapshot_id` alongside this result without the two ever
    disagreeing."""

    company_id: uuid.UUID
    period_start: dt.date
    period_end: dt.date
    num_months: int
    assumptions: ScenarioAssumptionsIn
    baseline: ScenarioKpis
    scenario: ScenarioKpis
    deltas: ScenarioDeltas
    applied: AppliedChangesRead
