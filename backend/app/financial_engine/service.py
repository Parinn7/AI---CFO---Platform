"""Financial engine service (Phase 4). DB-backed operations that use the
deterministic engine helpers — no LLM (architecture §4.1).

`auto_categorize_company` fills in `category_id` for a company's uncategorized
transactions using the rule-based `guess_category`. It's applied on demand (an
endpoint/button) and is also reused inline during upload for rows that arrive
without a category.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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
