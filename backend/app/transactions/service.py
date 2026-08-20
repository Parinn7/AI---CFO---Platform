"""Upload/transaction service (task 3.2).

Bridges the DB-free parser (`parsing.py`) and the database: it resolves each
parsed row's category and final income/expense `type` against the company's
categories, then persists an `UploadBatch` and its `Transaction`s.

Type resolution order (first that applies wins):
  1. an explicit type/direction column in the file;
  2. the matched category's type;
  3. the sign of the amount (negative → expense, otherwise income).
The stored `amount` is always the positive magnitude — direction lives in `type`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.transactions.models import Category, Transaction, UploadBatch
from app.transactions.parsing import (
    ParsedRow,
    UploadParseError,
    parse_upload,
)

# 10 MB cap (NFR-5). Checked before parsing so oversized files fail fast.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


async def _category_lookup(
    db: AsyncSession, company_id: uuid.UUID
) -> dict[str, Category]:
    """Case-insensitive name -> Category for this company's usable categories
    (system defaults + any the company owns)."""
    result = await db.execute(
        select(Category).where(
            or_(Category.company_id.is_(None), Category.company_id == company_id)
        )
    )
    return {c.name.strip().lower(): c for c in result.scalars().all()}


def _resolve_type(row: ParsedRow, category: Category | None) -> str:
    if row.explicit_type is not None:
        return row.explicit_type
    if category is not None:
        return category.type
    return "expense" if row.amount < 0 else "income"


async def process_upload(
    db: AsyncSession,
    company_id: uuid.UUID,
    filename: str,
    content: bytes,
) -> tuple[UploadBatch, list[Transaction]]:
    """Parse `content` and persist a batch + its transactions.

    Raises UploadParseError on file-level problems (unsupported type, empty
    file, missing required columns, oversize) — the router turns those into 400s.
    """
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadParseError("File is too large (10 MB maximum).")

    parsed = parse_upload(filename, content)  # may raise UploadParseError
    categories = await _category_lookup(db, company_id)

    batch = UploadBatch(
        company_id=company_id,
        filename=filename,
        status="processing",
        row_count=0,
        error_log=None,
    )
    db.add(batch)
    await db.flush()  # assign batch.id before creating transactions

    transactions: list[Transaction] = []
    for row in parsed.rows:
        category = (
            categories.get(row.category_name.strip().lower())
            if row.category_name
            else None
        )
        txn = Transaction(
            company_id=company_id,
            category_id=category.id if category else None,
            source="upload",
            upload_batch_id=batch.id,
            date=row.date,
            description=row.description,
            amount=abs(row.amount) if isinstance(row.amount, Decimal) else row.amount,
            type=_resolve_type(row, category),
        )
        db.add(txn)
        transactions.append(txn)

    batch.row_count = len(transactions)
    batch.error_log = "\n".join(parsed.errors) if parsed.errors else None
    batch.status = "completed"

    await db.commit()
    await db.refresh(batch)
    for txn in transactions:
        await db.refresh(txn)
    return batch, transactions


async def list_batches(
    db: AsyncSession, company_id: uuid.UUID
) -> list[UploadBatch]:
    result = await db.execute(
        select(UploadBatch)
        .where(UploadBatch.company_id == company_id)
        .order_by(UploadBatch.created_at.desc())
    )
    return list(result.scalars().all())


async def get_batch(
    db: AsyncSession, batch_id: uuid.UUID, company_id: uuid.UUID
) -> UploadBatch | None:
    result = await db.execute(
        select(UploadBatch).where(
            UploadBatch.id == batch_id, UploadBatch.company_id == company_id
        )
    )
    return result.scalar_one_or_none()


async def get_batch_for_user(
    db: AsyncSession, batch_id: uuid.UUID, owner_id: uuid.UUID
) -> UploadBatch | None:
    """Return the batch only if it belongs to a company owned by `owner_id`."""
    result = await db.execute(
        select(UploadBatch)
        .join(Company, Company.id == UploadBatch.company_id)
        .where(UploadBatch.id == batch_id, Company.owner_user_id == owner_id)
    )
    return result.scalar_one_or_none()


async def list_transactions_for_batch(
    db: AsyncSession, batch_id: uuid.UUID
) -> list[Transaction]:
    result = await db.execute(
        select(Transaction)
        .where(Transaction.upload_batch_id == batch_id)
        .order_by(Transaction.date, Transaction.created_at)
    )
    return list(result.scalars().all())
