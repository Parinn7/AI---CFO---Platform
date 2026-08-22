"""Financial-engine read endpoints (task 4.2, FR-3.2/FR-3.3).

Deterministic aggregations over a company's transactions — revenue/expense
totals and monthly cash flow. No LLM performs any of this math (architecture
§4.1 / SRS FR-6.6). All routes require a session and are scoped to a company the
caller owns; the router is mounted under `{api_v1_prefix}` in `app.main`.

Note on ordering: FastAPI matches routes in declaration order, so the auto-
categorize/edit/delete transaction routes live on the `transactions` router
(task 3.x/4.1). This `financial` router is a separate prefix to keep the
"reporting/read" surface distinct from the "data-input" surface.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.service import get_company_for_user
from app.core.database import get_db
from app.financial_engine import service
from app.financial_engine.schemas import (
    CashFlowResponse,
    FinancialSummary,
    KpiSnapshotCreate,
    KpiSnapshotRead,
    MonthlyCashFlowRead,
)

router = APIRouter(prefix="/financial", tags=["financial"])


async def _require_company(
    company_id: uuid.UUID, user: User, db: AsyncSession
) -> None:
    if await get_company_for_user(db, company_id, user.id) is None:
        # 404 (not 403) so we don't reveal whether the company exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )


def _check_range(start_date: dt.date | None, end_date: dt.date | None) -> None:
    if start_date is not None and end_date is not None and start_date > end_date:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start_date must not be after end_date.",
        )


@router.get("/summary", response_model=FinancialSummary)
async def financial_summary(
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FinancialSummary:
    """Total revenue vs. expenses (and net) over an optional [start, end] range
    (FR-3.2). Omit the dates for all-time totals."""
    await _require_company(company_id, current_user, db)
    _check_range(start_date, end_date)
    totals = await service.company_totals(db, company_id, start_date, end_date)
    return FinancialSummary(
        company_id=company_id,
        start_date=start_date,
        end_date=end_date,
        total_income=totals.total_income,
        total_expenses=totals.total_expenses,
        net=totals.net,
        income_count=totals.income_count,
        expense_count=totals.expense_count,
    )


@router.get("/cash-flow", response_model=CashFlowResponse)
async def cash_flow(
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CashFlowResponse:
    """Per-calendar-month inflow/outflow/net over an optional [start, end] range
    (FR-3.3). Only months with transactions are returned, oldest→newest."""
    await _require_company(company_id, current_user, db)
    _check_range(start_date, end_date)
    months = await service.company_cash_flow(db, company_id, start_date, end_date)
    return CashFlowResponse(
        company_id=company_id,
        start_date=start_date,
        end_date=end_date,
        months=[
            MonthlyCashFlowRead(
                month=m.month, inflow=m.inflow, outflow=m.outflow, net=m.net
            )
            for m in months
        ],
    )


@router.post(
    "/kpi-snapshots",
    response_model=KpiSnapshotRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_kpi_snapshot(
    payload: KpiSnapshotCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> KpiSnapshotRead:
    """Compute and store a KPI snapshot for a company over a period (FR-4.1–4.5):
    burn rate, runway, gross/operating margin, revenue growth. Deterministic —
    the AI CFO only ever reads these, never computes them (architecture §4.1)."""
    await _require_company(payload.company_id, current_user, db)
    snapshot = await service.generate_kpi_snapshot(
        db, payload.company_id, payload.period_start, payload.period_end
    )
    return KpiSnapshotRead.model_validate(snapshot)


@router.get("/kpi-snapshots", response_model=list[KpiSnapshotRead])
async def list_kpi_snapshots(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[KpiSnapshotRead]:
    """List a company's stored KPI snapshots, most recent period first."""
    await _require_company(company_id, current_user, db)
    snapshots = await service.list_kpi_snapshots(db, company_id)
    return [KpiSnapshotRead.model_validate(s) for s in snapshots]
