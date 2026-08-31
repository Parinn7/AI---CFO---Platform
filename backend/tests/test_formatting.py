"""INR and date rendering (`app/core/formatting.py`, task 7.2).

These matter because the same stored figure is written down in three places —
the dashboard, the AI CFO's context, and (from Phase 8) reports — and a founder
reading two different-looking renderings of one number has to stop and work out
whether they're the same. The expectations here mirror `frontend/lib/format.ts`.
"""

import datetime as dt

import pytest

from app.core.formatting import (
    format_compact_inr,
    format_date,
    format_inr,
    format_month,
    format_money,
    format_months,
    format_pct,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", "₹0.00"),
        ("999.4", "₹999.40"),
        ("1200", "₹1,200.00"),
        # Indian grouping: three digits, then pairs.
        ("120000", "₹1,20,000.00"),
        ("56000000", "₹5,60,00,000.00"),
        ("-421573.5", "-₹4,21,573.50"),
        # Rounded to paise, half up.
        ("1.005", "₹1.01"),
    ],
)
def test_format_inr(value: str, expected: str):
    assert format_inr(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("999", "₹999"),
        ("1200", "₹1.2K"),
        ("421573.50", "₹4.2L"),
        ("56000000", "₹5.6Cr"),
        ("-421573.50", "-₹4.2L"),
        # A trailing .0 is dropped, as on the dashboard's axis labels.
        ("500000", "₹5L"),
    ],
)
def test_format_compact_inr(value: str, expected: str):
    assert format_compact_inr(value) == expected


def test_format_money_names_a_magnitude_only_when_there_is_one():
    """Below a lakh there's no magnitude worth naming, and '₹1,200.00 (₹1.2K)'
    is noise rather than help."""
    assert format_money("1200") == "₹1,200.00"
    assert format_money("421573.50") == "₹4,21,573.50 (₹4.2L)"


def test_percentages_and_months():
    assert format_pct("-9.03") == "-9.0%"
    assert format_pct("70.05", signed=True) == "+70.1%"
    assert format_pct("-9.03", signed=True) == "-9.0%"
    # Runway keeps its trailing zero, matching the dashboard's tile exactly.
    assert format_months("17.29") == "17.3"
    assert format_months("6") == "6.0"


def test_dates_are_unambiguous():
    """No all-numeric ordering — 03/04 means different months either side of an
    ocean."""
    assert format_date(dt.date(2025, 8, 1)) == "1 Aug 2025"
    assert format_month(2025, 12) == "Dec 2025"
