"""Scenario models — see `database/schema.md` §7.

`Scenario` is a **saved** simulation (task 6.4, FR-5.4). Running a scenario is
still stateless (architecture §5.2); only an explicit save writes a row here.

What a row holds, and why:

* `assumptions` — the levers, stored verbatim in the shape fixed by
  `frontend/lib/scenarios.ts` and `ScenarioAssumptionsIn`, so a saved scenario
  can be loaded straight back into the input form and re-run.
* `result` — the before/after comparison **as it was computed at save time**,
  stored rather than re-derived (schema §7). Revisiting a saved scenario must
  show the same numbers it showed when saved; re-deriving would silently
  restate history every time the company adds a transaction. Re-running against
  today's data is a deliberate, separate action.
* `baseline_kpi_snapshot_id` — the `kpi_snapshots` row the comparison was made
  against, for traceability.

Both jsonb columns hold *deterministically computed* figures — an LLM is never
involved in producing or reading them (architecture §4.1).
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.models import TimestampMixin, UUIDPrimaryKeyMixin

# jsonb on Postgres (schema §7); plain JSON on SQLite, which the test suite uses.
JsonColumn = JSONB().with_variant(JSON(), "sqlite")


class Scenario(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One saved what-if for a company (FR-5.4).

    `created_at` is the save time (schema §7's `created_at`); `updated_at` comes
    from the shared mixin like every other table, though nothing currently
    mutates a saved scenario — a scenario is a record of a question that was
    asked, so changing one would rewrite the answer alongside it.
    """

    __tablename__ = "scenarios"

    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)

    assumptions: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)

    # Nullable + SET NULL (a widening of schema.md, which left it unmarked):
    # losing the snapshot row must not delete the user's saved scenario, and the
    # figures it was compared against are already inside `result` anyway.
    baseline_kpi_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("kpi_snapshots.id", ondelete="SET NULL"), nullable=True
    )

    result: Mapped[dict[str, Any]] = mapped_column(JsonColumn, nullable=False)
