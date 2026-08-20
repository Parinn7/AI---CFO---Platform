"""categories table + seed default INR/SME category set

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-20

Creates `categories` (database/schema.md §3) and seeds the system-default set
(company_id NULL) from the SRS. The seed list below is a FROZEN copy of
`app.transactions.categories.DEFAULT_CATEGORIES` — deliberately inlined so this
migration's behaviour never changes if that constant is later edited.
"""

import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Frozen snapshot of the default categories at the time of this migration.
_DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Revenue", "income"),
    ("Payroll", "expense"),
    ("Rent", "expense"),
    ("Marketing", "expense"),
    ("Software/Tools", "expense"),
    ("Operations", "expense"),
    ("Other", "expense"),
]


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "type IN ('income', 'expense')", name="ck_categories_type"
        ),
    )
    op.create_index("ix_categories_company_id", "categories", ["company_id"])

    # Seed the system defaults (company_id NULL). created_at/updated_at fall back
    # to their server defaults.
    categories = sa.table(
        "categories",
        sa.column("id", sa.Uuid()),
        sa.column("company_id", sa.Uuid()),
        sa.column("name", sa.Text()),
        sa.column("type", sa.Text()),
    )
    op.bulk_insert(
        categories,
        [
            {
                "id": uuid.uuid4(),
                "company_id": None,
                "name": name,
                "type": type_,
            }
            for name, type_ in _DEFAULT_CATEGORIES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_categories_company_id", table_name="categories")
    op.drop_table("categories")
