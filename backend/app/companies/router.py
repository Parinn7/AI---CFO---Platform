"""Company profile endpoints (task 2.3, FR-1.3) — create / list / get / update.

Every route requires a valid session (`get_current_user`) and is scoped to the
authenticated user, so one user can never read or mutate another's company.
Mounted under `{api_v1_prefix}/companies` in `app.main`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.companies import service
from app.companies.schemas import CompanyCreate, CompanyRead, CompanyUpdate
from app.core.database import get_db

router = APIRouter(prefix="/companies", tags=["companies"])

_not_found = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Company not found."
)


@router.post("", response_model=CompanyRead, status_code=status.HTTP_201_CREATED)
async def create_company(
    data: CompanyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    company = await service.create_company(db, current_user.id, data)
    return CompanyRead.model_validate(company)


@router.get("", response_model=list[CompanyRead])
async def list_companies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[CompanyRead]:
    companies = await service.list_companies_for_user(db, current_user.id)
    return [CompanyRead.model_validate(c) for c in companies]


@router.get("/{company_id}", response_model=CompanyRead)
async def get_company(
    company_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    company = await service.get_company_for_user(db, company_id, current_user.id)
    if company is None:
        raise _not_found
    return CompanyRead.model_validate(company)


@router.patch("/{company_id}", response_model=CompanyRead)
async def update_company(
    company_id: uuid.UUID,
    data: CompanyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> CompanyRead:
    company = await service.get_company_for_user(db, company_id, current_user.id)
    if company is None:
        raise _not_found
    company = await service.update_company(db, company, data)
    return CompanyRead.model_validate(company)
