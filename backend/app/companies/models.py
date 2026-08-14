"""Company model (`companies` table) — see `database/schema.md` §2.

MVP: single owner per company; currency fixed to INR. `company_id` is the
scoping key for all financial data added in later phases — every company-scoped
query must filter by it (NFR-3, no cross-company leakage).
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.auth.models import User


class Company(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "companies"
    __table_args__ = (
        CheckConstraint(
            "fiscal_year_start_month BETWEEN 1 AND 12",
            name="ck_companies_fiscal_year_start_month",
        ),
    )

    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    fiscal_year_start_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="INR")

    owner: Mapped[User] = relationship(back_populates="companies")
