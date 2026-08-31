"""Display formatting for INR amounts and dates, server-side.

Mirrors `frontend/lib/format.ts` deliberately. The AI CFO's context block and
(from Phase 8) generated reports quote the same stored figures the dashboard
shows, and a founder reading "₹4,21,573.50/mo" on one screen and "₹422000/mo"
in an answer has to stop and check whether they're the same number.

Formatting is *rendering*, not calculation — the values arrive already computed
by the Financial Engine (architecture §4.1). Nothing here derives a figure; it
only decides how an existing one is written down.
"""

from __future__ import annotations

import datetime as dt
from decimal import ROUND_HALF_UP, Decimal

_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)

_CENTS = Decimal("0.01")
_TENTH = Decimal("0.1")

LAKH = Decimal("100000")
CRORE = Decimal("10000000")
THOUSAND = Decimal("1000")


def _group_indian(digits: str) -> str:
    """Indian digit grouping: last three digits, then pairs — 12345678 →
    '1,23,45,678'."""
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    parts = []
    while len(head) > 2:
        parts.append(head[-2:])
        head = head[:-2]
    if head:
        parts.append(head)
    return ",".join(reversed(parts)) + "," + tail


def format_inr(value: Decimal | float | str) -> str:
    """Full INR amount with Indian grouping, always 2 dp — '₹1,20,000.00'."""
    amount = Decimal(str(value)).quantize(_CENTS, rounding=ROUND_HALF_UP)
    sign = "-" if amount < 0 else ""
    whole, _, frac = abs(amount).__str__().partition(".")
    return f"{sign}₹{_group_indian(whole)}.{frac or '00'}"


def _trim(value: Decimal) -> str:
    """One decimal place, with a trailing '.0' dropped — 4.20 → '4.2', 5.0 → '5'."""
    text = str(value.quantize(_TENTH, rounding=ROUND_HALF_UP))
    return text[:-2] if text.endswith(".0") else text


def format_compact_inr(value: Decimal | float | str) -> str:
    """INR in the magnitudes Indians actually speak in — '₹4.2L', '₹5.6Cr'.

    Below ₹1,000 there's no magnitude worth naming, so the amount is written out
    to the rupee."""
    amount = Decimal(str(value))
    sign = "-" if amount < 0 else ""
    abs_amount = abs(amount)
    if abs_amount >= CRORE:
        return f"{sign}₹{_trim(abs_amount / CRORE)}Cr"
    if abs_amount >= LAKH:
        return f"{sign}₹{_trim(abs_amount / LAKH)}L"
    if abs_amount >= THOUSAND:
        return f"{sign}₹{_trim(abs_amount / THOUSAND)}K"
    return f"{sign}₹{abs_amount.quantize(Decimal('1'), rounding=ROUND_HALF_UP)}"


def format_money(value: Decimal | float | str) -> str:
    """An amount written both ways when the magnitude is worth naming —
    '₹4,21,573.50 (₹4.2L)'.

    Both renderings are the *same stored number*: the exact figure is the one of
    record, and the compact form is there so plain-language answers (FR-6.3) can
    use it without anyone converting anything."""
    exact = format_inr(value)
    if abs(Decimal(str(value))) < LAKH:
        return exact
    return f"{exact} ({format_compact_inr(value)})"


def format_pct(value: Decimal | float | str, *, signed: bool = False) -> str:
    """A percentage to 1 dp — '-9.0%', or '+70.1%' when `signed` (growth reads
    better with its direction stated)."""
    pct = Decimal(str(value)).quantize(_TENTH, rounding=ROUND_HALF_UP)
    lead = "+" if signed and pct >= 0 else ""
    return f"{lead}{pct}%"


def format_date(value: dt.date) -> str:
    """'1 Aug 2025' — unambiguous, unlike any all-numeric ordering."""
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"


def format_month(year: int, month: int) -> str:
    """'Aug 2025'."""
    return f"{_MONTHS[month - 1]} {year}"


def format_months(value: Decimal | float | str) -> str:
    """A month count, always to 1 dp — '17.3', '17.0'. Matches the dashboard's
    runway tile exactly, trailing zero included, so the two never look like
    different numbers."""
    return str(Decimal(str(value)).quantize(_TENTH, rounding=ROUND_HALF_UP))
