"""Financial engine service (Phase 4). DB-backed operations that use the
deterministic engine helpers — no LLM (architecture §4.1).

`auto_categorize_company` fills in `category_id` for a company's uncategorized
transactions using the rule-based `guess_category`. It's applied on demand (an
endpoint/button) and is also reused inline during upload for rows that arrive
without a category.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.financial_engine.calculations import (
    MonthlyCashFlow,
    Totals,
    compute_monthly_cash_flow,
    compute_totals,
)
from app.financial_engine.categorization import guess_category
from app.transactions.models import Transaction
from app.transactions.service import list_categories


async def auto_categorize_company(
    db: AsyncSession, company_id: uuid.UUID
) -> tuple[int, int]:
    """Assign categories to the company's uncategorized transactions.

    Returns `(categorized, uncategorized_remaining)`. Only rows the rules can
    confidently match are touched; the rest stay uncategorized.
    """
    result = await db.execute(
        select(Transaction).where(
            Transaction.company_id == company_id,
            Transaction.category_id.is_(None),
        )
    )
    transactions = list(result.scalars().all())

    by_name = {c.name.lower(): c for c in await list_categories(db, company_id)}

    categorized = 0
    for txn in transactions:
        guessed = guess_category(txn.description, txn.type)
        if guessed is None:
            continue
        category = by_name.get(guessed.lower())
        if category is not None:
            txn.category_id = category.id
            categorized += 1

    if categorized:
        await db.commit()

    return categorized, len(transactions) - categorized


# --- Revenue/expense totals + cash flow (task 4.2, FR-3.2/FR-3.3) ---


async def _load_rows(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None,
    end_date: dt.date | None,
) -> list[tuple[dt.date, object, str]]:
    """Load `(date, amount, type)` for a company's transactions, optionally
    bounded by an inclusive date range. Selecting only the three columns the
    math needs keeps the aggregation cheap and source-agnostic — upload and
    manual entries are summed identically (FR-2.6)."""
    stmt = select(
        Transaction.date, Transaction.amount, Transaction.type
    ).where(Transaction.company_id == company_id)
    if start_date is not None:
        stmt = stmt.where(Transaction.date >= start_date)
    if end_date is not None:
        stmt = stmt.where(Transaction.date <= end_date)
    result = await db.execute(stmt)
    return [tuple(row) for row in result.all()]


async def company_totals(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> Totals:
    """Total revenue vs. expenses for a company over an optional period
    (FR-3.2). Deterministic — no LLM."""
    rows = await _load_rows(db, company_id, start_date, end_date)
    return compute_totals(rows)


async def company_cash_flow(
    db: AsyncSession,
    company_id: uuid.UUID,
    start_date: dt.date | None = None,
    end_date: dt.date | None = None,
) -> list[MonthlyCashFlow]:
    """Per-month inflow/outflow/net for a company over an optional period
    (FR-3.3). Deterministic — no LLM."""
    rows = await _load_rows(db, company_id, start_date, end_date)
    return compute_monthly_cash_flow(rows)
