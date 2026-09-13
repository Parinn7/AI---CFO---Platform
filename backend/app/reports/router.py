"""Report endpoints (Phase 8, FR-7.x) — the monthly report (8.1), the board
report (8.2), the investor readiness summary (8.3) and the PDF export of all
three (8.4).

Read-only: generating a report never writes one, and **neither does exporting
it**. Each `/pdf` route runs exactly the same generator as its JSON sibling and
hands the result to `reports.pdf` to draw, so an export can't state anything the
screen doesn't — and nothing is stored, which is why the `reports` table in
`schema.md` §10 was retired rather than built. This is a `GET` and repeating it
is free. The one write it can cause is indirect — a reported
period's KPI snapshot is get-or-created through the Financial Engine's normal
path, so a report and the dashboard reference the same `kpi_snapshots` row
rather than each minting their own.

Owner-scoped like every company-scoped route, 404 rather than 403 so the
endpoint doesn't confirm that a company id exists.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.models import Company
from app.companies.service import get_company_for_user
from app.core.database import get_db
from app.reports import pdf, service
from app.reports.schemas import BoardReport, InvestorSummary, MonthlyReport

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


def _parse_month_arg(month: str | None) -> tuple[int, int] | None:
    """`"2026-07"` → `(2026, 7)`, `None` → `None`, anything else → 400."""
    if month is None:
        return None
    try:
        return service.parse_month(month)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc


#: The 404 body for a company with nothing recorded. Shared so the JSON route
#: and its PDF sibling can't drift into saying different things about the same
#: condition.
NO_DATA_DETAIL = (
    "No financial data yet — import a file or add entries before "
    "generating a report."
)


def _no_data() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_DATA_DETAIL)


def _pdf_response(content: bytes, filename: str) -> Response:
    """A rendered report as a file download.

    `Content-Disposition: attachment` rather than `inline`: the browser is
    fetching this with an `Authorization` header via `fetch`, not navigating to
    it, so it arrives as a blob the page saves under this name — the filename is
    the only thing that tells a founder which report and which period they're
    looking at once it's in their downloads folder.

    The frontend can only *read* that header because `main.py` lists it in the
    CORS policy's `expose_headers` — a cross-origin page gets the bytes but not
    the headers by default. It is set there rather than here because it is a
    property of the policy, and a header set on one response is silently
    overwritten if the CORS middleware ever starts sending its own.
    """
    return Response(
        content=content,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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

    parsed = _parse_month_arg(month)

    try:
        return await service.generate_monthly_report(db, company, parsed)
    except service.NoFinancialData:
        raise _no_data()


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

    parsed = _parse_month_arg(end_month)

    try:
        return await service.generate_board_report(db, company, period, parsed)
    except service.NoFinancialData:
        raise _no_data()


@router.get("/investor", response_model=InvestorSummary)
async def investor_summary(
    company_id: uuid.UUID,
    end_month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> InvestorSummary:
    """The Investor Readiness Summary (FR-7.3) — the metrics investors typically
    evaluate over a trailing year, and a fixed-threshold checklist of how the
    company reads against them: run-rate and its annualisation, the year against
    the year before it, cash at both ends, burn efficiency, and six graded
    checks.

    The grading is a fixed rule over Financial Engine output, not a judgement
    and not a model's opinion — `financial_engine/readiness.py` holds the
    thresholds, and the summary carries them alongside each verdict so the
    screen states the rule rather than keeping its own copy.

    `end_month` is `YYYY-MM`; omit it for the latest month with data. A
    malformed one is a `400`; a company with no transactions at all a `404`.
    """
    company = await _require_company(company_id, current_user, db)

    parsed = _parse_month_arg(end_month)

    try:
        return await service.generate_investor_summary(db, company, parsed)
    except service.NoFinancialData:
        raise _no_data()


# --- PDF export (task 8.4, FR-7.4) ---
#
# Each export is its JSON sibling plus a renderer. The generator call is
# identical — same owner check, same window rules, same `NoFinancialData` 404 —
# so the exported copy and the screen it was exported from are the same report
# by construction, not by two implementations agreeing. Nothing is written to
# disk or to the database; see `reports/pdf.py` and `schema.md` §10.


@router.get(
    "/monthly/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def monthly_report_pdf(
    company_id: uuid.UUID,
    month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Monthly Financial Report as a downloadable PDF (FR-7.4).

    Same arguments and same behaviour as `GET /reports/monthly` — `month` is
    `YYYY-MM`, omitted for the latest month with data — rendered rather than
    serialised.
    """
    company = await _require_company(company_id, current_user, db)
    parsed = _parse_month_arg(month)

    try:
        report = await service.generate_monthly_report(db, company, parsed)
    except service.NoFinancialData:
        raise _no_data()

    return _pdf_response(
        pdf.render_monthly_report(report), pdf.monthly_filename(report)
    )


@router.get(
    "/board/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def board_report_pdf(
    company_id: uuid.UUID,
    period: Literal["quarter", "year"] = "quarter",
    end_month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Board Report as a downloadable PDF (FR-7.4).

    Same arguments and same behaviour as `GET /reports/board` — a trailing
    quarter (default) or year, anchored on `end_month` or on the latest month
    with data.
    """
    company = await _require_company(company_id, current_user, db)
    parsed = _parse_month_arg(end_month)

    try:
        report = await service.generate_board_report(db, company, period, parsed)
    except service.NoFinancialData:
        raise _no_data()

    return _pdf_response(pdf.render_board_report(report), pdf.board_filename(report))


@router.get(
    "/investor/pdf",
    response_class=Response,
    responses={200: {"content": {"application/pdf": {}}}},
)
async def investor_summary_pdf(
    company_id: uuid.UUID,
    end_month: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The Investor Readiness Summary as a downloadable PDF (FR-7.4).

    Same arguments and same behaviour as `GET /reports/investor` — a trailing
    year anchored on `end_month` or on the latest month with data, with the six
    readiness checks and the fixed thresholds they were graded against.
    """
    company = await _require_company(company_id, current_user, db)
    parsed = _parse_month_arg(end_month)

    try:
        report = await service.generate_investor_summary(db, company, parsed)
    except service.NoFinancialData:
        raise _no_data()

    return _pdf_response(
        pdf.render_investor_summary(report), pdf.investor_filename(report)
    )
