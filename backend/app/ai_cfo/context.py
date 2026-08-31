"""AI CFO context assembly (task 7.2, FR-6.2 / architecture §4.1).

**What the assistant is allowed to know.** Everything numeric in the context
comes from one `kpi_snapshots` row — figures the Financial Engine already
computed and stored. Raw transactions are never read here and never rendered:
not the descriptions, not the amounts, not the dates. That isn't caution about
privacy, it's the architectural boundary in §4.1 — hand a model a list of
transactions and "what's my burn rate?" and it will do the arithmetic itself,
which is exactly the failure mode this platform exists to avoid.

The non-numeric facts (company name, industry) come from `companies`, because
"you're a SaaS business" changes how a figure should be explained without being
a figure itself.

This module is **pure and DB-free**, like `financial_engine/calculations.py` and
`scenarios/simulation.py`: it takes a stored snapshot and a company row and
returns a value object plus its rendered text. Choosing *which* snapshot is the
service's job (`ai_cfo.service.build_context`).

**Undefined figures are stated, not hidden.** Runway, margins and growth are
each null in a real case — not burning cash, out of cash, no revenue, no prior
period. Dropping a null from the context would let the model infer the figure is
zero or simply unknown; saying "not applicable, and here's why" is the only
rendering that can't mislead.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.companies.models import Company
from app.core.formatting import (
    format_date,
    format_money,
    format_months,
    format_pct,
)
from app.financial_engine.models import KpiSnapshot

NOT_APPLICABLE = "Not applicable"

# The runway below which founders and investors generally treat the situation as
# urgent. Stated as *where this company sits relative to it* rather than as a
# bare threshold: the note is handed to the model verbatim, and "under 6 months
# is urgent" printed beside a 17-month runway is an invitation to alarm.
URGENT_RUNWAY_MONTHS = Decimal("6")


@dataclass(frozen=True)
class Figure:
    """One precomputed number, as the assistant should see it.

    `value` is the rendered figure (or `NOT_APPLICABLE`), `meaning` says what it
    measures in plain language, and `note` carries the caveat that goes with
    *this* company's value — why it's undefined, or which direction is good."""

    key: str
    label: str
    value: str
    meaning: str
    note: str = ""


@dataclass(frozen=True)
class CfoContext:
    """Everything the AI CFO is given for one answer.

    `snapshot_id` is written to `chat_messages.kpi_context_snapshot_id`, which
    is what makes §4.1 checkable after the fact: the exact row of figures behind
    an answer can be pulled up and compared against what the answer said."""

    company_id: uuid.UUID
    company_name: str
    industry: str | None
    currency: str
    period_start: dt.date
    period_end: dt.date
    num_months: int
    snapshot_id: uuid.UUID
    computed_at: dt.datetime
    figures: tuple[Figure, ...]


def _months_spanned(period_start: dt.date, period_end: dt.date) -> int:
    return (
        (period_end.year - period_start.year) * 12
        + (period_end.month - period_start.month)
        + 1
    )


def _burn_figure(burn: Decimal) -> Figure:
    """Burn rate, signed the way the engine stores it: positive means cash is
    leaving. A surplus is the same number negative, and reads far better stated
    as a surplus than as "negative burn"."""
    burning = burn > 0
    return Figure(
        key="burn_rate",
        label="Burn rate",
        value=(
            f"{format_money(burn)} per month"
            if burning
            else f"{format_money(-burn)} per month of surplus"
        ),
        meaning=(
            "Average net cash leaving the business each month over the period "
            "(expenses minus revenue, divided by the number of months)."
        ),
        note=(
            "The company is spending more than it earns."
            if burning
            else "The company is cash-generative — it earned more than it spent."
        ),
    )


def _runway_figure(runway: Decimal | None, burn: Decimal) -> Figure:
    """Runway, with the *reason* when it's undefined.

    Two very different situations both store null (`calculations.compute_kpis`):
    not burning cash, and having no cash left. Telling them apart matters more
    than almost anything else in this block — one is good news and the other is
    an emergency — and the burn rate distinguishes them without any new
    arithmetic."""
    if runway is not None:
        return Figure(
            key="runway_months",
            label="Runway",
            value=f"{format_months(runway)} months",
            meaning=(
                "How many months the cash on hand lasts at the current burn "
                "rate, if nothing changes."
            ),
            note=(
                "Below the six months usually treated as urgent."
                if runway < URGENT_RUNWAY_MONTHS
                else "Above the six months usually treated as urgent."
            ),
        )
    if burn > 0:
        note = (
            "The company is burning cash but has no positive cash balance left "
            "on the books, so there is no runway to measure. This is the "
            "serious case, not the safe one."
        )
    else:
        note = (
            "The company is not burning cash, so there is nothing to run out "
            "of. Runway only means something while money is going out faster "
            "than it comes in."
        )
    return Figure(
        key="runway_months",
        label="Runway",
        value=NOT_APPLICABLE,
        meaning=(
            "How many months the cash on hand lasts at the current burn rate."
        ),
        note=note,
    )


def _margin_figure(margin: Decimal | None) -> Figure:
    if margin is None:
        return Figure(
            key="gross_margin_pct",
            label="Margin",
            value=NOT_APPLICABLE,
            meaning="Profit as a percentage of revenue.",
            note=(
                "There was no revenue in this period, so a margin cannot be "
                "expressed as a percentage of it."
            ),
        )
    return Figure(
        key="gross_margin_pct",
        label="Margin",
        value=format_pct(margin),
        meaning=(
            "Profit as a percentage of revenue — revenue minus all expenses, "
            "divided by revenue. Cost of goods sold is not tracked separately "
            "in this system, so gross and operating margin are the same figure."
        ),
        note=(
            "Positive means the period was profitable."
            if margin >= 0
            else "Negative means the period ran at a loss."
        ),
    )


def _growth_figure(growth: Decimal | None, num_months: int) -> Figure:
    window = f"the {num_months} months before it"
    if growth is None:
        return Figure(
            key="revenue_growth_pct",
            label="Revenue growth",
            value=NOT_APPLICABLE,
            meaning=f"Change in revenue versus {window}.",
            note=(
                "There is no recorded revenue in the preceding period to "
                "compare against, so growth cannot be measured yet."
            ),
        )
    return Figure(
        key="revenue_growth_pct",
        label="Revenue growth",
        value=format_pct(growth, signed=True),
        meaning=f"Change in revenue versus {window}.",
        note="Measured against the real prior period, not a projection.",
    )


def build_figures(snapshot: KpiSnapshot) -> tuple[Figure, ...]:
    """Render a stored snapshot's columns as the context's figure list.

    Every value here is read straight off the snapshot. Nothing is derived,
    combined or recomputed — the only judgement applied is *how to say it*."""
    burn = Decimal(str(snapshot.burn_rate))
    num_months = _months_spanned(snapshot.period_start, snapshot.period_end)
    return (
        Figure(
            key="total_revenue",
            label="Total revenue",
            value=format_money(snapshot.total_revenue),
            meaning="All money that came into the business over the period.",
        ),
        Figure(
            key="total_expenses",
            label="Total expenses",
            value=format_money(snapshot.total_expenses),
            meaning="All money that went out over the period.",
        ),
        Figure(
            key="net_cash_flow",
            label="Net cash flow",
            value=format_money(snapshot.net_cash_flow),
            meaning="Revenue minus expenses over the period.",
            note=(
                "Negative means the period consumed cash."
                if Decimal(str(snapshot.net_cash_flow)) < 0
                else "Positive means the period generated cash."
            ),
        ),
        _burn_figure(burn),
        _runway_figure(
            None
            if snapshot.runway_months is None
            else Decimal(str(snapshot.runway_months)),
            burn,
        ),
        _margin_figure(
            None
            if snapshot.gross_margin_pct is None
            else Decimal(str(snapshot.gross_margin_pct))
        ),
        _growth_figure(
            None
            if snapshot.revenue_growth_pct is None
            else Decimal(str(snapshot.revenue_growth_pct)),
            num_months,
        ),
    )


def from_snapshot(company: Company, snapshot: KpiSnapshot) -> CfoContext:
    """Assemble the context for a company from one stored KPI snapshot."""
    return CfoContext(
        company_id=company.id,
        company_name=company.name,
        industry=company.industry,
        currency=company.currency,
        period_start=snapshot.period_start,
        period_end=snapshot.period_end,
        num_months=_months_spanned(snapshot.period_start, snapshot.period_end),
        snapshot_id=snapshot.id,
        computed_at=snapshot.created_at,
        figures=build_figures(snapshot),
    )


def render(context: CfoContext) -> str:
    """The context as the block of text that goes into the prompt (7.3/7.4).

    Rendered here rather than inside the prompt template so that what the model
    is given is a testable value with a stable shape, and so the same block can
    be shown to the user — an assistant whose inputs you can read is one you can
    argue with."""
    lines = [
        "COMPANY",
        f"- Name: {context.company_name}",
    ]
    if context.industry:
        lines.append(f"- Industry: {context.industry}")
    lines.append(f"- Currency: {context.currency} (Indian rupees)")
    lines += [
        "",
        "PERIOD",
        f"- {format_date(context.period_start)} to "
        f"{format_date(context.period_end)} ({context.num_months} months)",
        f"- Figures computed by the Financial Engine on "
        f"{format_date(context.computed_at.date())} "
        f"(snapshot {context.snapshot_id}).",
        "",
        "FIGURES (already calculated — quote these, never recalculate them)",
    ]
    for figure in context.figures:
        lines.append(f"- {figure.label}: {figure.value}")
        lines.append(f"    What it measures: {figure.meaning}")
        if figure.note:
            lines.append(f"    Note: {figure.note}")
    return "\n".join(lines)


__all__ = [
    "NOT_APPLICABLE",
    "CfoContext",
    "Figure",
    "build_figures",
    "from_snapshot",
    "render",
]
