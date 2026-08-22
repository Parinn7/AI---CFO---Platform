"""kpi_snapshots table

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-22

Creates `kpi_snapshots` (schema.md §6) — precomputed per-company, per-period KPI
values the AI CFO reads from (task 4.3, FR-4.1–4.5). Totals/net/burn are
non-null; runway, margins and growth are nullable (undefined cases: not burning
cash, zero revenue, no prior period). Composite index on
(company_id, period_start, period_end) for period lookups (schema.md §Indexes).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "kpi_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("total_revenue", sa.Numeric(14, 2), nullable=False),
        sa.Column("total_expenses", sa.Numeric(14, 2), nullable=False),
        sa.Column("net_cash_flow", sa.Numeric(14, 2), nullable=False),
        sa.Column("burn_rate", sa.Numeric(14, 2), nullable=False),
        sa.Column("runway_months", sa.Numeric(6, 2), nullable=True),
        sa.Column("gross_margin_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("operating_margin_pct", sa.Numeric(6, 2), nullable=True),
        sa.Column("revenue_growth_pct", sa.Numeric(6, 2), nullable=True),
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
    )
    op.create_index(
        "ix_kpi_snapshots_company_period",
        "kpi_snapshots",
        ["company_id", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("ix_kpi_snapshots_company_period", table_name="kpi_snapshots")
    op.drop_table("kpi_snapshots")
