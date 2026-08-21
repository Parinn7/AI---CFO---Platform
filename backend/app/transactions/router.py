"""Data-input endpoints (Phase 3) — CSV/XLSX upload (3.2, FR-2.1/2.2), the
category list + guided manual entry (3.3, FR-2.3), and a company transactions
list.

All routes require a session and are scoped to a company the caller owns
(reusing `companies.service.get_company_for_user`), so no cross-company access.
The three routers here are mounted under `{api_v1_prefix}` in `app.main`.
"""

from __future__ import annotations

import uuid

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies.service import get_company_for_user
from app.core.database import get_db
from app.transactions import service
from app.transactions.parsing import UploadParseError
from app.transactions.schemas import (
    CategoryRead,
    ManualEntryResult,
    ManualTransactionBatch,
    TransactionRead,
    UploadBatchRead,
    UploadResult,
)

router = APIRouter(prefix="/uploads", tags=["uploads"])


async def _require_company(
    company_id: uuid.UUID, user: User, db: AsyncSession
) -> None:
    if await get_company_for_user(db, company_id, user.id) is None:
        # 404 (not 403) so we don't reveal whether the company exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
        )


@router.post("", response_model=UploadResult, status_code=status.HTTP_201_CREATED)
async def upload_file(
    company_id: uuid.UUID = Form(...),
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResult:
    """Upload and import a CSV/XLSX file of transactions for a company."""
    await _require_company(company_id, current_user, db)

    content = await file.read()
    try:
        batch, transactions = await service.process_upload(
            db, company_id, file.filename or "upload", content
        )
    except UploadParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return UploadResult(batch=UploadBatchRead.model_validate(batch), transactions=transactions)


@router.get("", response_model=list[UploadBatchRead])
async def list_uploads(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[UploadBatchRead]:
    """List a company's upload batches, newest first."""
    await _require_company(company_id, current_user, db)
    batches = await service.list_batches(db, company_id)
    return [UploadBatchRead.model_validate(b) for b in batches]


@router.get("/{batch_id}", response_model=UploadResult)
async def get_upload(
    batch_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UploadResult:
    """Get one batch plus the transactions it imported."""
    batch = await service.get_batch_for_user(db, batch_id, current_user.id)
    if batch is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Upload not found."
        )
    transactions = await service.list_transactions_for_batch(db, batch.id)
    return UploadResult(
        batch=UploadBatchRead.model_validate(batch), transactions=transactions
    )


# --- Categories (task 3.3) — powers the guided manual-entry prompts ---

categories_router = APIRouter(prefix="/categories", tags=["categories"])


@categories_router.get("", response_model=list[CategoryRead])
async def list_categories(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CategoryRead]:
    """List the categories a company can use (system defaults + its own)."""
    await _require_company(company_id, current_user, db)
    categories = await service.list_categories(db, company_id)
    return [CategoryRead.model_validate(c) for c in categories]


# --- Transactions (task 3.3) — guided manual entry + list ---

transactions_router = APIRouter(prefix="/transactions", tags=["transactions"])


@transactions_router.post(
    "", response_model=ManualEntryResult, status_code=status.HTTP_201_CREATED
)
async def create_manual_transactions(
    payload: ManualTransactionBatch,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ManualEntryResult:
    """Create one or more manual (`source="manual"`) transactions from the
    guided flow. Entries land in the same table as uploads (FR-2.6); exact
    duplicates are skipped and reported (FR-2.4)."""
    await _require_company(payload.company_id, current_user, db)
    try:
        created, skipped = await service.create_manual_transactions(
            db, payload.company_id, payload.transactions
        )
    except service.ManualEntryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )
    return ManualEntryResult(
        created=[TransactionRead.model_validate(t) for t in created],
        skipped_duplicates=skipped,
    )


@transactions_router.get("", response_model=list[TransactionRead])
async def list_transactions(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[TransactionRead]:
    """List a company's transactions (upload + manual), newest first."""
    await _require_company(company_id, current_user, db)
    txns = await service.list_transactions(db, company_id)
    return [TransactionRead.model_validate(t) for t in txns]
