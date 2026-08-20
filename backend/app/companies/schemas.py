"""Pydantic request/response schemas for company profiles (task 2.3, FR-1.3).

Currency is intentionally *not* a client input: the product is INR-only for the
MVP (see `schema.md` §2), so the server always stores/returns "INR". It appears
in `CompanyRead` for the frontend to display, but can't be set or changed.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CompanyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)


class CompanyUpdate(BaseModel):
    """All fields optional — only those provided are changed (PATCH semantics)."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    industry: str | None = Field(default=None, max_length=200)
    fiscal_year_start_month: int | None = Field(default=None, ge=1, le=12)


class CompanyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str
    industry: str | None
    fiscal_year_start_month: int | None
    currency: str
    created_at: datetime
    updated_at: datetime
