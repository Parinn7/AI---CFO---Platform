"""Default category set (task 3.1) — the simplified INR/SME categories from the
SRS. Living, app-level source of truth used at runtime (auto-categorization,
manual entry, category listings in later phases).

These are seeded as *system defaults* (`company_id IS NULL`) by Alembic migration
`0002`, which keeps its own frozen copy of this list — a migration must not change
behaviour if this constant is later edited. Keep the two in sync when adding a
default.
"""

from __future__ import annotations

# Allowed category types (mirrors the DB check constraint on `categories.type`).
CATEGORY_TYPES = ("income", "expense")

# (name, type). Order is the intended display order. Revenue is the only income
# category in the MVP set; everything else is an expense bucket.
DEFAULT_CATEGORIES: list[tuple[str, str]] = [
    ("Revenue", "income"),
    ("Payroll", "expense"),
    ("Rent", "expense"),
    ("Marketing", "expense"),
    ("Software/Tools", "expense"),
    ("Operations", "expense"),
    ("Other", "expense"),
]
