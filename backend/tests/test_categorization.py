"""Unit tests for deterministic auto-categorization (task 4.1) — no DB needed."""

import pytest

from app.financial_engine.categorization import guess_category


@pytest.mark.parametrize("description", ["Payment from client", "", None, "anything"])
def test_income_is_always_revenue(description):
    assert guess_category(description, "income") == "Revenue"


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Monthly office rent", "Rent"),  # 'rent' wins before 'office'
        ("Salary payment to staff", "Payroll"),
        ("Google Ads campaign spend", "Marketing"),
        ("AWS hosting subscription", "Software/Tools"),
        ("Bulk inventory purchase", "Operations"),
        ("Electricity and water bill", "Operations"),
    ],
)
def test_expense_keyword_matching(description, expected):
    assert guess_category(description, "expense") == expected


@pytest.mark.parametrize("description", ["Mystery blob xyz", "", None, "misc thing"])
def test_expense_no_match_returns_none(description):
    assert guess_category(description, "expense") is None


def test_whole_word_matching_avoids_false_positives():
    # 'rent' is a substring of 'different' but not a whole word.
    assert guess_category("a different approach", "expense") is None
    # 'ads' is a substring of 'roadside' but not a whole word.
    assert guess_category("roadside repair", "expense") is None


def test_case_insensitive():
    assert guess_category("MONTHLY RENT", "expense") == "Rent"
