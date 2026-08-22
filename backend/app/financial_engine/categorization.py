"""Deterministic auto-categorization (task 4.1, FR-3.1).

Rule-based, DB-free, and unit-testable — **no LLM** (architecture §4.1). Given a
transaction's description and income/expense `type`, guess a category *name*:

  * income → "Revenue" (the only income category in the MVP set), always.
  * expense → the first keyword rule whose word appears in the description;
    `None` if nothing matches (leave it uncategorized rather than guess wrongly).

Matching is on whole words (the description is tokenized), so "rent" won't fire
on "different" and "ads" won't fire on "roads". Returned names line up with the
seeded defaults in `app.transactions.categories.DEFAULT_CATEGORIES`.
"""

from __future__ import annotations

import re

# Ordered: first rule that matches wins. Names must match seeded categories.
# Keywords are whole words (lowercased) expected to appear in the description.
EXPENSE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("Payroll", ("salary", "salaries", "payroll", "wage", "wages", "stipend", "bonus")),
    ("Rent", ("rent", "rental", "lease", "landlord")),
    (
        "Marketing",
        ("marketing", "ads", "ad", "advert", "advertising", "advertisement",
         "campaign", "seo", "promotion", "promo"),
    ),
    (
        "Software/Tools",
        ("software", "saas", "subscription", "subscriptions", "license", "licence",
         "hosting", "domain", "aws", "azure", "gcp", "github", "figma", "slack",
         "notion", "zoom", "adobe"),
    ),
    (
        "Operations",
        ("operations", "purchase", "purchases", "supplies", "inventory",
         "logistics", "shipping", "freight", "utilities", "electricity", "water",
         "internet", "office", "maintenance", "travel", "fuel", "transport"),
    ),
]


def guess_category(description: str | None, txn_type: str) -> str | None:
    """Return a category name for a transaction, or None if no rule matches."""
    if txn_type == "income":
        return "Revenue"

    words = set(re.findall(r"[a-z]+", (description or "").lower()))
    if not words:
        return None
    for name, keywords in EXPENSE_KEYWORDS:
        if words.intersection(keywords):
            return name
    return None
