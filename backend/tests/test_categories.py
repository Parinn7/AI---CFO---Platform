"""Unit tests for the default category set (task 3.1).

The actual seeding happens in Alembic migration 0002 (verified live against
Supabase); here we just lock down the shape of the app-level constant that
downstream phases (auto-categorization, manual entry) will read.
"""

from app.transactions.categories import CATEGORY_TYPES, DEFAULT_CATEGORIES


def test_default_set_matches_srs():
    names = [name for name, _ in DEFAULT_CATEGORIES]
    assert names == [
        "Revenue",
        "Payroll",
        "Rent",
        "Marketing",
        "Software/Tools",
        "Operations",
        "Other",
    ]


def test_all_types_are_valid():
    assert all(type_ in CATEGORY_TYPES for _, type_ in DEFAULT_CATEGORIES)


def test_revenue_is_the_only_income_category():
    income = [name for name, type_ in DEFAULT_CATEGORIES if type_ == "income"]
    assert income == ["Revenue"]


def test_no_duplicate_names():
    names = [name for name, _ in DEFAULT_CATEGORIES]
    assert len(names) == len(set(names))
