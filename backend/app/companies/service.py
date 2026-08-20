"""Company service layer — owner-scoped profile CRUD.

Every read/write is scoped by `owner_user_id` so a user can only ever see or
mutate their own companies (NFR-3, no cross-company data leakage). Keeping the
scoping here means routers just pass the authenticated user through.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.companies.schemas import CompanyCreate, CompanyUpdate


async def create_company(
    db: AsyncSession, owner_id: uuid.UUID, data: CompanyCreate
) -> Company:
    company = Company(
        owner_user_id=owner_id,
        name=data.name,
        industry=data.industry,
        fiscal_year_start_month=data.fiscal_year_start_month,
        # currency omitted — DB server_default fixes it to INR (INR-only MVP).
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return company


async def list_companies_for_user(
    db: AsyncSession, owner_id: uuid.UUID
) -> list[Company]:
    result = await db.execute(
        select(Company)
        .where(Company.owner_user_id == owner_id)
        .order_by(Company.created_at)
    )
    return list(result.scalars().all())


async def get_company_for_user(
    db: AsyncSession, company_id: uuid.UUID, owner_id: uuid.UUID
) -> Company | None:
    """Return the company only if it exists AND belongs to `owner_id`."""
    result = await db.execute(
        select(Company).where(
            Company.id == company_id, Company.owner_user_id == owner_id
        )
    )
    return result.scalar_one_or_none()


async def update_company(
    db: AsyncSession, company: Company, data: CompanyUpdate
) -> Company:
    # exclude_unset: only overwrite fields the client actually sent.
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(company, field, value)
    await db.commit()
    await db.refresh(company)
    return company
