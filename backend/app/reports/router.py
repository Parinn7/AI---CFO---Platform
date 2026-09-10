"""Report endpoints (Phase 8, FR-7.x) — the monthly report (8.1) and the
board report (8.2).

Read-only: generating a report never writes one (see `reports.service` for why
there is no `reports` row until PDF export in 8.4), so this is a `GET` and
repeating it is free. The one write it can cause is indirect — a reported
period's KPI snapshot is get-or-created through the Financial Engine's normal
path, so a report and the dashboard reference the same `kpi_snapshots` row
rather than each minting their own.

Owner-scoped like every company-scoped route, 404 rather than 403 so the
endpoint doesn't confirm that a company id exists.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.models import Company
from app.companies.service import get_company_for_user
from app.core.database import get_db
from app.reports import service
from app.reports.schemas import BoardReport, MonthlyReport

router = APIRouter(prefix="/reports", tags=["reports"])


async def _require_company(
    company_id: uuid.UUID, user: User, db: AsyncSession
) -> Company:
    company = await get_company_for_user(db, company_id, user.id)
    if company is None:
        # 404 (not 403) so we don't reveal whether the company exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )
    return company


@router.get("/monthly", response_model=MonthlyReport)
async def monthly_report(
    company_id: uuid.UUID,
    month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MonthlyReport:
    """The Monthly Financial Report for one calendar month (FR-7.1) — revenue,
    expenses, cash flow and KPIs, plus the category breakdown, the movement
    against the previous month, a six-month trend and the month's flagged
    expenses.

    `month` is `YYYY-MM`; omit it for the latest month the company has data for.
    A month with no transactions still reports (honest zeros); a company with no
    transactions at all is a `404` — there is no month to report on.
    """
    company = await _require_company(company_id, current_user, db)

    parsed = None
    if month is not None:
        try:
            parsed = service.parse_month(month)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    try:
        return await service.generate_monthly_report(db, company, parsed)
    except service.NoFinancialData:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No financial data yet — import a file or add entries before "
                "generating a report."
            ),
        )


@router.get("/board", response_model=BoardReport)
async def board_report(
    company_id: uuid.UUID,
    period: Literal["quarter", "year"] = "quarter",
    end_month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> BoardReport:
    """The Board Report (FR-7.2) — a trailing quarter (default) or year, aimed
    at a reader who wasn't in the building: the period's KPIs beside the
    equal-length period before them, cash at both ends, the month-by-month
    shape, the cost structure, the flagged spend being watched, and the saved
    scenarios currently on the table.

    `end_month` is `YYYY-MM`; omit it for the latest month with data. Naming it
    is how a calendar or fiscal quarter is produced — `period=quarter` with
    `end_month=2026-03` is Jan–Mar. An unknown `period` is a `422`; a malformed
    `end_month` a `400`; a company with no transactions at all a `404`.
    """
    company = await _require_company(company_id, current_user, db)

    parsed = None
    if end_month is not None:
        try:
            parsed = service.parse_month(end_month)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            ) from exc

    try:
        return await service.generate_board_report(db, company, period, parsed)
    except service.NoFinancialData:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "No financial data yet — import a file or add entries before "
                "generating a report."
            ),
        )
