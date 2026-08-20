"""upload_batches and transactions tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-20

Creates `upload_batches` (schema.md §5) and `transactions` (§4). Transactions
reference companies, categories (nullable, SET NULL on delete) and the upload
batch they came from (nullable, CASCADE). `type` and `source` are guarded by
check constraints; `amount` is numeric(14,2), stored as a positive magnitude.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_batches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("error_log", sa.Text(), nullable=True),
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
            "status IN ('processing', 'completed', 'failed')",
            name="ck_upload_batches_status",
        ),
    )
    op.create_index(
        "ix_upload_batches_company_id", "upload_batches", ["company_id"]
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("category_id", sa.Uuid(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("upload_batch_id", sa.Uuid(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column(
            "is_flagged_anomaly",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
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
        sa.ForeignKeyConstraint(
            ["category_id"], ["categories.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["upload_batch_id"], ["upload_batches.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "source IN ('upload', 'manual')", name="ck_transactions_source"
        ),
        sa.CheckConstraint(
            "type IN ('income', 'expense')", name="ck_transactions_type"
        ),
    )
    op.create_index("ix_transactions_company_id", "transactions", ["company_id"])
    op.create_index("ix_transactions_category_id", "transactions", ["category_id"])
    op.create_index(
        "ix_transactions_upload_batch_id", "transactions", ["upload_batch_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_transactions_upload_batch_id", table_name="transactions")
    op.drop_index("ix_transactions_category_id", table_name="transactions")
    op.drop_index("ix_transactions_company_id", table_name="transactions")
    op.drop_table("transactions")
    op.drop_index("ix_upload_batches_company_id", table_name="upload_batches")
    op.drop_table("upload_batches")
