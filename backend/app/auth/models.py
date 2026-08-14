"""User model (`users` table) — see `database/schema.md` §1.

MVP: a user owns one or more companies. Authentication (signup/login, JWT) is
built on top of this in task 2.2; this task only establishes the table.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.companies.models import Company


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)

    companies: Mapped[list[Company]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
