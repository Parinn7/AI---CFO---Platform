"""Category model (`categories` table) — see `database/schema.md` §3.

A category is either a **system default** (`company_id IS NULL`, seeded by
migration `0002` from `DEFAULT_CATEGORIES`) or company-specific (custom
categories are post-MVP). `type` is `income` | `expense`, enforced by a check
constraint. Transactions (task 3.2) reference categories via `category_id`.
"""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin


class Category(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        CheckConstraint(
            "type IN ('income', 'expense')", name="ck_categories_type"
        ),
    )

    # Nullable: NULL = system default category shared across all companies.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
