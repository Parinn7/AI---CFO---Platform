"""Pydantic schemas for the financial engine (Phase 4)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, model_validator


class AutoCategorizeRequest(BaseModel):
    company_id: uuid.UUID


class AutoCategorizeResult(BaseModel):
    """Outcome of an auto-categorization run over a company's uncategorized
    transactions."""

    categorized: int
    uncategorized_remaining: int


# --- Revenue/expense totals + cash flow (task 4.2, FR-3.2/FR-3.3) ---


class FinancialSummary(BaseModel):
    """Total revenue vs. expenses over an optional period (FR-3.2). `net` is
    income minus expenses; a negative net means the company spent more than it
    earned in the window. `start_date`/`end_date` echo the requested bounds
    (null = unbounded)."""

    company_id: uuid.UUID
    start_date: dt.date | None
    end_date: dt.date | None
    total_income: Decimal
    total_expenses: Decimal
    net: Decimal
    income_count: int
    expense_count: int


class MonthlyCashFlowRead(BaseModel):
    """One calendar month's cash movement (FR-3.3)."""

    month: str  # "YYYY-MM"
    inflow: Decimal
    outflow: Decimal
    net: Decimal


class CashFlowResponse(BaseModel):
    """Per-month inflow/outflow/net over an optional period (FR-3.3). Only
    months with transactions are present; ordered oldest→newest."""

    company_id: uuid.UUID
    start_date: dt.date | None
    end_date: dt.date | None
    months: list[MonthlyCashFlowRead]


# --- KPI snapshots (task 4.3, FR-4.1–4.5) ---


class KpiSnapshotCreate(BaseModel):
    """Request to compute + store a KPI snapshot for a company over a period."""

    company_id: uuid.UUID
    period_start: dt.date
    period_end: dt.date

    @model_validator(mode="after")
    def _ordered(self) -> "KpiSnapshotCreate":
        if self.period_start > self.period_end:
            raise ValueError("period_start must not be after period_end.")
        return self


class KpiSnapshotRead(BaseModel):
    """A stored KPI snapshot (schema.md §6). Runway/margins/growth are null in
    their undefined cases (not burning cash, zero revenue, no prior period)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    period_start: dt.date
    period_end: dt.date
    total_revenue: Decimal
    total_expenses: Decimal
    net_cash_flow: Decimal
    burn_rate: Decimal
    runway_months: Decimal | None
    gross_margin_pct: Decimal | None
    operating_margin_pct: Decimal | None
    revenue_growth_pct: Decimal | None
    created_at: dt.datetime
