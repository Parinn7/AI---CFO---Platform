"""Pydantic schemas for the financial engine (Phase 4)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel


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
