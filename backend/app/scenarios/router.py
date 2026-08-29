"""Scenario Simulator endpoints (tasks 6.2/6.4, FR-5.2–FR-5.4).

Two things live here, and the split is deliberate (architecture §5.2):

* `POST /scenarios/simulate` — **stateless**. Computes a before/after comparison
  and returns it without writing anything, which is why it answers 200, not 201.
* `POST /scenarios`, `GET /scenarios`, `GET|DELETE /scenarios/{id}` — saving and
  revisiting (6.4, FR-5.4). Saving re-runs the simulation server-side and
  persists the result; revisiting replays what was stored rather than
  recomputing, so a saved scenario keeps stating the answer it gave when saved.

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
from app.scenarios.models import Scenario
from app.scenarios.schemas import (
    ScenarioRead,
    ScenarioSaveRequest,
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

    return service.simulation_payload(
        payload.company_id, Assumptions(**payload.assumptions.model_dump()), result
    )


@router.post("", response_model=ScenarioRead, status_code=status.HTTP_201_CREATED)
async def save_scenario(
    payload: ScenarioSaveRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioRead:
    """Save a scenario so it can be revisited later (FR-5.4).

    The simulation is re-run here from the submitted levers — the client never
    supplies a result — so what gets stored can only be deterministic engine
    output (architecture §4.1). 201: unlike `/simulate`, this one creates a row.
    """
    await _require_company(payload.company_id, current_user, db)

    scenario = await service.save_scenario(
        db,
        payload.company_id,
        payload.name,
        payload.period_start,
        payload.period_end,
        Assumptions(**payload.assumptions.model_dump()),
    )
    return ScenarioRead.model_validate(scenario)


@router.get("", response_model=list[ScenarioRead])
async def list_scenarios(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ScenarioRead]:
    """A company's saved scenarios, newest first (FR-5.4).

    Each carries its full stored comparison, so the list can render a saved
    scenario without a second request — and every figure in it is the one
    computed at save time, not a recomputation against today's data.
    """
    await _require_company(company_id, current_user, db)
    scenarios = await service.list_scenarios(db, company_id)
    return [ScenarioRead.model_validate(s) for s in scenarios]


async def _require_scenario(
    scenario_id: uuid.UUID, user: User, db: AsyncSession
) -> Scenario:
    scenario = await service.get_scenario_for_user(db, scenario_id, user.id)
    if scenario is None:
        # 404 (not 403) so we don't reveal whether the scenario exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Scenario not found."
        )
    return scenario


@router.get("/{scenario_id}", response_model=ScenarioRead)
async def get_scenario(
    scenario_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ScenarioRead:
    """Revisit one saved scenario (FR-5.4) — replayed from storage, not
    recomputed."""
    return ScenarioRead.model_validate(
        await _require_scenario(scenario_id, current_user, db)
    )


@router.delete("/{scenario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_scenario(
    scenario_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Discard a saved scenario. Transactions and KPI snapshots are untouched."""
    scenario = await _require_scenario(scenario_id, current_user, db)
    await service.delete_scenario(db, scenario)
