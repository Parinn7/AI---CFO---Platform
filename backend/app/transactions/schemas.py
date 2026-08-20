"""Pydantic response schemas for uploads + transactions (task 3.2)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    category_id: uuid.UUID | None
    source: str
    upload_batch_id: uuid.UUID | None
    date: dt.date
    description: str | None
    amount: Decimal
    type: str
    is_flagged_anomaly: bool
    created_at: dt.datetime


class UploadBatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID
    filename: str
    status: str
    row_count: int
    error_log: str | None
    created_at: dt.datetime


class UploadResult(BaseModel):
    """Returned by POST /uploads and GET /uploads/{id}: the batch plus the
    transactions it produced."""

    batch: UploadBatchRead
    transactions: list[TransactionRead]
