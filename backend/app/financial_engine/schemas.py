"""Pydantic schemas for the financial engine (Phase 4)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel


class AutoCategorizeRequest(BaseModel):
    company_id: uuid.UUID


class AutoCategorizeResult(BaseModel):
    """Outcome of an auto-categorization run over a company's uncategorized
    transactions."""

    categorized: int
    uncategorized_remaining: int
