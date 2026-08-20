"""Structural tests for the Phase 2.1 models — no database required.

These assert the ORM metadata matches database/schema.md §1–2, so the models
and the migration can't silently drift apart.
"""

from app.core.database import Base
from app.auth import models as _auth  # noqa: F401
from app.companies import models as _companies  # noqa: F401
from app.transactions import models as _transactions  # noqa: F401


def test_expected_tables_registered():
    assert set(Base.metadata.tables) == {"users", "companies", "categories"}


def test_users_columns():
    cols = Base.metadata.tables["users"].columns
    assert {"id", "email", "password_hash", "full_name", "created_at", "updated_at"} <= set(
        cols.keys()
    )
    assert cols["email"].unique is True
    assert cols["email"].nullable is False
    assert cols["password_hash"].nullable is False


def test_companies_columns_and_constraints():
    table = Base.metadata.tables["companies"]
    cols = table.columns
    assert {
        "id",
        "owner_user_id",
        "name",
        "industry",
        "fiscal_year_start_month",
        "currency",
    } <= set(cols.keys())
    # INR default, single-owner FK to users, fiscal-month check constraint.
    assert cols["currency"].server_default is not None
    fk = list(cols["owner_user_id"].foreign_keys)[0]
    assert fk.column.table.name == "users"
    constraint_names = {c.name for c in table.constraints if c.name}
    assert "ck_companies_fiscal_year_start_month" in constraint_names


def test_categories_columns_and_constraints():
    table = Base.metadata.tables["categories"]
    cols = table.columns
    assert {"id", "company_id", "name", "type"} <= set(cols.keys())
    # company_id is nullable (NULL = system default) and FKs to companies.
    assert cols["company_id"].nullable is True
    assert cols["name"].nullable is False
    assert cols["type"].nullable is False
    fk = list(cols["company_id"].foreign_keys)[0]
    assert fk.column.table.name == "companies"
    constraint_names = {c.name for c in table.constraints if c.name}
    assert "ck_categories_type" in constraint_names
