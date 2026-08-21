"""Pydantic schemas for uploads + transactions (tasks 3.2, 3.3)."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CategoryRead(BaseModel):
    """A category the guided manual-entry flow can offer (system default or the
    company's own)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    company_id: uuid.UUID | None  # NULL = system default
    name: str
    type: str


class ManualTransactionInput(BaseModel):
    """One answered prompt in the guided flow. Amount is a positive magnitude;
    `type` is optional when a category is given (it's taken from the category)."""

    date: dt.date
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    category_id: uuid.UUID | None = None
    type: Literal["income", "expense"] | None = None
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _needs_type_or_category(self) -> "ManualTransactionInput":
        if self.type is None and self.category_id is None:
            raise ValueError("Each entry needs a category or an explicit type.")
        return self


class ManualTransactionBatch(BaseModel):
    """The guided form submits every filled-in prompt at once."""

    company_id: uuid.UUID
    transactions: list[ManualTransactionInput] = Field(min_length=1)


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


class ManualEntryResult(BaseModel):
    """Response for POST /transactions: what was saved, and which entries were
    skipped as duplicates (FR-2.4)."""

    created: list[TransactionRead]
    skipped_duplicates: list[str]
