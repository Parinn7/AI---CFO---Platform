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

import datetime as dt
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
from app.transactions.schemas import ManualTransactionInput, TransactionUpdate

# 10 MB cap (NFR-5). Checked before parsing so oversized files fail fast.
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


class ManualEntryError(Exception):
    """A manual entry references a category the caller can't use."""


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


# --- Duplicate detection (task 3.4, FR-2.4) ---
#
# Two transactions are considered duplicates when they share a company and the
# same (date, amount, type, description). Category is intentionally excluded so a
# re-import still matches even if categorization differs. This catches the common
# cases — re-uploading the same file, or re-submitting the guided form — while
# accepting that genuinely-identical entries (two ₹50 coffees, same note, same
# day) can't be told apart and will be treated as one.

_Signature = tuple[dt.date, Decimal, str, str]


def _signature(
    date: dt.date, amount: Decimal, txn_type: str, description: str | None
) -> _Signature:
    return (
        date,
        Decimal(amount).quantize(Decimal("0.01")),
        txn_type,
        (description or "").strip().lower(),
    )


async def _existing_signatures(
    db: AsyncSession, company_id: uuid.UUID
) -> set[_Signature]:
    """Signatures of the company's existing transactions, for dedupe checks."""
    result = await db.execute(
        select(
            Transaction.date,
            Transaction.amount,
            Transaction.type,
            Transaction.description,
        ).where(Transaction.company_id == company_id)
    )
    return {_signature(d, a, t, desc) for d, a, t, desc in result.all()}


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

    # Seed with existing signatures so re-imports AND within-file repeats are
    # both caught as duplicates (FR-2.4).
    seen = await _existing_signatures(db, company_id)
    messages = list(parsed.errors)

    transactions: list[Transaction] = []
    for row in parsed.rows:
        category = (
            categories.get(row.category_name.strip().lower())
            if row.category_name
            else None
        )
        txn_type = _resolve_type(row, category)
        amount = abs(row.amount) if isinstance(row.amount, Decimal) else row.amount

        signature = _signature(row.date, amount, txn_type, row.description)
        if signature in seen:
            messages.append(
                f"Row {row.source_row}: duplicate of an existing transaction — skipped."
            )
            continue
        seen.add(signature)

        txn = Transaction(
            company_id=company_id,
            category_id=category.id if category else None,
            source="upload",
            upload_batch_id=batch.id,
            date=row.date,
            description=row.description,
            amount=amount,
            type=txn_type,
        )
        db.add(txn)
        transactions.append(txn)

    batch.row_count = len(transactions)
    batch.error_log = "\n".join(messages) if messages else None
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


# --- Categories + manual entry (task 3.3) ---


async def list_categories(
    db: AsyncSession, company_id: uuid.UUID
) -> list[Category]:
    """Categories the company can use: system defaults (`company_id IS NULL`)
    plus any it owns. Ordered defaults-first, then by name."""
    result = await db.execute(
        select(Category)
        .where(
            or_(Category.company_id.is_(None), Category.company_id == company_id)
        )
        .order_by(Category.company_id.is_(None).desc(), Category.name)
    )
    return list(result.scalars().all())


async def create_manual_transactions(
    db: AsyncSession,
    company_id: uuid.UUID,
    entries: list[ManualTransactionInput],
) -> tuple[list[Transaction], list[str]]:
    """Create `source="manual"` transactions from the guided flow.

    Returns `(created, skipped_duplicate_messages)`. Entries that duplicate an
    existing transaction (or a another entry in the same submission) are skipped
    and reported rather than double-entered (FR-2.4). Manual entries are
    first-class — they land in the same `transactions` table as uploads (FR-2.6),
    differing only by `source` and a null `upload_batch_id`.
    Raises ManualEntryError if an entry names a category the company can't use.
    """
    usable = {c.id: c for c in await list_categories(db, company_id)}
    seen = await _existing_signatures(db, company_id)

    created: list[Transaction] = []
    skipped: list[str] = []
    for entry in entries:
        category = None
        if entry.category_id is not None:
            category = usable.get(entry.category_id)
            if category is None:
                raise ManualEntryError("Unknown or inaccessible category.")

        txn_type = entry.type or (category.type if category else None)
        if txn_type is None:  # schema guarantees this, belt-and-suspenders
            raise ManualEntryError("Each entry needs a category or a type.")

        signature = _signature(entry.date, entry.amount, txn_type, entry.description)
        if signature in seen:
            label = entry.description or (category.name if category else txn_type)
            skipped.append(
                f"{entry.date}: {label} (₹{entry.amount}) looks like a duplicate — skipped."
            )
            continue
        seen.add(signature)

        txn = Transaction(
            company_id=company_id,
            category_id=entry.category_id,
            source="manual",
            upload_batch_id=None,
            date=entry.date,
            description=entry.description,
            amount=entry.amount,  # schema enforces > 0 (positive magnitude)
            type=txn_type,
        )
        db.add(txn)
        created.append(txn)

    await db.commit()
    for txn in created:
        await db.refresh(txn)
    return created, skipped


async def list_transactions(
    db: AsyncSession, company_id: uuid.UUID
) -> list[Transaction]:
    """All of a company's transactions (upload + manual), newest first."""
    result = await db.execute(
        select(Transaction)
        .where(Transaction.company_id == company_id)
        .order_by(Transaction.date.desc(), Transaction.created_at.desc())
    )
    return list(result.scalars().all())


# --- Edit / delete a single transaction (task 3.5, FR-2.5) ---


async def get_transaction_for_user(
    db: AsyncSession, transaction_id: uuid.UUID, owner_id: uuid.UUID
) -> Transaction | None:
    """Return the transaction only if it belongs to a company owned by `owner_id`."""
    result = await db.execute(
        select(Transaction)
        .join(Company, Company.id == Transaction.company_id)
        .where(Transaction.id == transaction_id, Company.owner_user_id == owner_id)
    )
    return result.scalar_one_or_none()


async def update_transaction(
    db: AsyncSession, transaction: Transaction, data: TransactionUpdate
) -> Transaction:
    """Apply a partial update. Only fields the client sent are changed; a
    supplied non-null `category_id` must be one the company can use.
    Raises ManualEntryError on an invalid category."""
    fields = data.model_dump(exclude_unset=True)

    if fields.get("category_id") is not None:
        usable = {c.id for c in await list_categories(db, transaction.company_id)}
        if fields["category_id"] not in usable:
            raise ManualEntryError("Unknown or inaccessible category.")

    for field, value in fields.items():
        setattr(transaction, field, value)

    await db.commit()
    await db.refresh(transaction)
    return transaction


async def delete_transaction(db: AsyncSession, transaction: Transaction) -> None:
    await db.delete(transaction)
    await db.commit()
