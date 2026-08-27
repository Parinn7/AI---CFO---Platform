"""Scenario Simulator endpoints (task 6.2, FR-5.2/FR-5.3).

One route for now: a **stateless** simulation. It computes a before/after
comparison and returns it without writing anything (architecture §5.2) — which
is why it answers 200, not 201. Saving a scenario to the `scenarios` table is
6.4's job.

All the arithmetic is deterministic Python in `scenarios.simulation` +
`financial_engine.calculations`; no LLM is involved (architecture §4.1 / SRS
FR-6.6). Routes require a session and are scoped to a company the caller owns.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.service import get_company_for_user
from app.core.database import get_db
from app.scenarios import service
from app.scenarios.schemas import (
    AppliedChangesRead,
    ScenarioDeltas,
    ScenarioKpis,
    ScenarioSimulateRequest,
    ScenarioSimulationRead,
)
from app.scenarios.simulation import Assumptions

router = APIRouter(prefix="/scenarios", tags=["scenarios"])


async def _require_company(
    company_id: uuid.UUID, user: User, db: AsyncSession
) -> None:
    if await get_company_for_user(db, company_id, user.id) is None:
        # 404 (not 403) so we don't reveal whether the company exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )


@router.post("/simulate", response_model=ScenarioSimulationRead)
async def simulate(
    payload: ScenarioSimulateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioSimulationRead:
    """Recalculate cash flow, runway, profitability and growth under a
    hypothetical, alongside the real figures for the same period (FR-5.2).

    Returns both sides plus per-metric deltas (FR-5.3) and an `applied` block
    showing what the levers actually did in rupees. Persists nothing.
    """
    await _require_company(payload.company_id, current_user, db)

    result = await service.simulate_scenario(
        db,
        payload.company_id,
        payload.period_start,
        payload.period_end,
        Assumptions(**payload.assumptions.model_dump()),
    )

    return ScenarioSimulationRead(
        company_id=payload.company_id,
        period_start=result.period_start,
        period_end=result.period_end,
        num_months=result.num_months,
        assumptions=payload.assumptions,
        baseline=ScenarioKpis(**vars(result.baseline)),
        scenario=ScenarioKpis(**vars(result.scenario)),
        deltas=ScenarioDeltas(**vars(result.deltas)),
        applied=AppliedChangesRead(**vars(result.applied)),
    )
