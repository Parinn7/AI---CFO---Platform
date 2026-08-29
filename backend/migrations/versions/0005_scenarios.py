"""scenarios table

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-29

Creates `scenarios` (schema.md §7) — saved what-if simulations (task 6.4,
FR-5.4). `assumptions` holds the levers verbatim; `result` holds the before/after
comparison as computed at save time (stored, not re-derived).
`baseline_kpi_snapshot_id` is nullable with ON DELETE SET NULL so losing a
snapshot never deletes a user's saved scenario. Index on
(company_id, created_at) for the "my saved scenarios, newest first" listing.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scenarios",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("assumptions", postgresql.JSONB(), nullable=False),
        sa.Column("baseline_kpi_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("result", postgresql.JSONB(), nullable=False),
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
            ["baseline_kpi_snapshot_id"], ["kpi_snapshots.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scenarios_company_created",
        "scenarios",
        ["company_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_scenarios_company_created", table_name="scenarios")
    op.drop_table("scenarios")
