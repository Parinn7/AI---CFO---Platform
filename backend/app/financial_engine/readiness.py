"""Investor-readiness assessment (task 8.3, FR-7.3).

Pure, DB-free, **no LLM** (architecture §4.1) — the same shape as `anomaly.py`,
and for the same reason. FR-7.3 asks for "key metrics investors typically
evaluate", which means two things this module produces from figures the
Financial Engine has already computed:

* **Run-rate and burn efficiency** — the derived figures an investor asks for on
  a first call that aren't already a KPI: the annualised revenue run-rate, and
  the burn multiple (cash burned per rupee of new revenue).
* **A readiness checklist** — six fixed-threshold checks over engine output.
  Each returns `ready` / `attention` / `gap` / `not_applicable` against a stated
  numeric threshold, exactly like the anomaly rule flags a category-month: a
  fixed rule applied to real figures, never a judgement and never a model's
  opinion. Thresholds are constants here, not per-company configuration.

**What this deliberately does not produce: a score.** There is no weighted total
and no grade, because a single number would imply a precision this data can't
support and would invite reading it as a valuation. The overall status is the
*weakest link* — the worst status among the checks — which is how a diligence
conversation actually goes: one six-month runway is not offset by a good margin.

Every threshold below is a conventional early-stage benchmark, and the summary
says so on its face. They are not claims about what any particular investor
requires.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from app.financial_engine.calculations import (
    ZERO,
    months_in_period,
    quantize_money,
)

#: Months in a year — the multiplier turning a month's revenue into an
#: annualised run-rate. Named because "× 12" appearing bare in a financial
#: calculation is the kind of thing that gets mis-read as a magic number.
MONTHS_PER_YEAR = 12

_CENTS = Decimal("0.01")

# Ratios share the KPI columns' clamp: a burn multiple over a near-zero
# denominator can run to absurd magnitudes, and an absurd figure is noise.
_RATIO_MAX = Decimal("9999.99")

CheckStatus = Literal["ready", "attention", "gap", "not_applicable"]

#: Statuses ordered worst-first, for picking the weakest link. `not_applicable`
#: is excluded: a check that couldn't be measured is not a finding.
_SEVERITY: tuple[CheckStatus, ...] = ("gap", "attention", "ready")


@dataclass(frozen=True)
class CheckSpec:
    """One readiness check: what it measures, and the fixed thresholds it is
    measured against.

    Every check is higher-is-better — a value at or above `ready_at` is ready,
    at or above `attention_at` is attention, below that is a gap. Keeping them
    all in one direction means the grading rule is one comparison rather than
    six special cases.
    """

    key: str
    label: str
    unit: str  # "months" | "pct"
    ready_at: Decimal
    attention_at: Decimal


#: The checklist, in the order an investor works through it: how long the
#: company has been measurable, how long it survives, whether it's growing,
#: whether the unit economics work, and whether the numbers can be trusted.
CHECK_SPECS: tuple[CheckSpec, ...] = (
    CheckSpec(
        key="track_record",
        label="Track record",
        unit="months",
        ready_at=Decimal("12"),
        attention_at=Decimal("6"),
    ),
    CheckSpec(
        key="runway",
        label="Runway",
        unit="months",
        ready_at=Decimal("12"),
        attention_at=Decimal("6"),
    ),
    CheckSpec(
        key="revenue_growth",
        label="Revenue growth",
        unit="pct",
        ready_at=Decimal("20"),
        attention_at=Decimal("0"),
    ),
    CheckSpec(
        key="operating_margin",
        label="Operating margin",
        unit="pct",
        ready_at=Decimal("0"),
        attention_at=Decimal("-50"),
    ),
    CheckSpec(
        key="revenue_consistency",
        label="Revenue consistency",
        unit="pct",
        ready_at=Decimal("90"),
        attention_at=Decimal("60"),
    ),
    CheckSpec(
        key="categorized_spend",
        label="Categorized spend",
        unit="pct",
        ready_at=Decimal("95"),
        attention_at=Decimal("80"),
    ),
)

_SPECS_BY_KEY = {spec.key: spec for spec in CHECK_SPECS}


@dataclass(frozen=True)
class CheckResult:
    """One graded check. `value` is the measured figure in the spec's unit, or
    None when the check couldn't be measured at all (`not_applicable`).

    `detail` is a plain-language statement of what was measured — a template
    filled with engine figures, so it can never disagree with `value`. It is
    built here rather than in the frontend because the same sentence has to
    appear in the PDF export (8.4), and two renderers writing it separately is
    two chances to word the same rule differently."""

    key: str
    label: str
    status: CheckStatus
    value: Decimal | None
    unit: str
    ready_at: Decimal
    attention_at: Decimal
    detail: str


@dataclass(frozen=True)
class ReadinessInputs:
    """Everything the checklist grades, all of it already computed elsewhere.

    Taking measured figures rather than a DB session is what keeps this module
    pure and the thresholds testable in isolation — the caller does the
    aggregation, this decides what the numbers mean.
    """

    months_of_history: int
    months_with_revenue: int
    runway_months: Decimal | None
    is_burning: bool
    revenue_growth_pct: Decimal | None
    operating_margin_pct: Decimal | None
    categorized_expense_pct: Decimal | None


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal:
    """Clamped 2-dp ratio, matching the KPI columns' precision."""
    value = (numerator / denominator).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return min(value, _RATIO_MAX)


def annualised_run_rate(monthly_revenue: Decimal) -> Decimal:
    """The latest month's revenue × 12 (ARR as an investor means it).

    Deliberately the *latest month*, not the trailing year's total ÷ 12: a
    run-rate answers "what is this business earning now", and averaging in the
    months before a company started selling understates it. The summary states
    the trailing-year total alongside, so a reader can see both.
    """
    return quantize_money(Decimal(monthly_revenue) * MONTHS_PER_YEAR)


def burn_multiple(
    net_burn: Decimal, revenue_now: Decimal, revenue_before: Decimal
) -> Decimal | None:
    """Rupees of net cash burned per rupee of new revenue — burn ÷ net new
    revenue.

    The standard read on whether money spent is buying growth. Returns None
    where the ratio has no meaning rather than a misleading number:

    * not burning (`net_burn <= 0`) — a profitable period has no burn to divide;
    * revenue flat or down — dividing by zero or a negative would produce a
      figure that looks like efficiency and isn't.

    `net_burn` is a positive magnitude (expenses − revenue over the period),
    matching `KpiValues.burn_rate`'s sign convention scaled to the whole window.
    """
    burn = Decimal(net_burn)
    new_revenue = Decimal(revenue_now) - Decimal(revenue_before)
    if burn <= ZERO or new_revenue <= ZERO:
        return None
    return _ratio(burn, new_revenue)


def months_of_history(first: dt.date, last: dt.date) -> int:
    """Inclusive count of calendar months spanned by the data on record.

    Months in the middle with nothing recorded still count — a company that
    invoiced in January and June has been measurable for six months, and the
    `revenue_consistency` check is what says the middle was quiet.
    """
    return months_in_period(first, last)


def _grade(spec: CheckSpec, value: Decimal) -> CheckStatus:
    if value >= spec.ready_at:
        return "ready"
    if value >= spec.attention_at:
        return "attention"
    return "gap"


def _pct(value: Decimal) -> str:
    """A percentage for prose: trailing zeros trimmed, so 12.00 reads "12"."""
    quantized = Decimal(value).quantize(_CENTS, rounding=ROUND_HALF_UP)
    return f"{quantized.normalize():f}"


def _months(value: Decimal) -> str:
    return f"{Decimal(value).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP):f}"


def _result(
    key: str, status: CheckStatus, value: Decimal | None, detail: str
) -> CheckResult:
    spec = _SPECS_BY_KEY[key]
    return CheckResult(
        key=spec.key,
        label=spec.label,
        status=status,
        value=value,
        unit=spec.unit,
        ready_at=spec.ready_at,
        attention_at=spec.attention_at,
        detail=detail,
    )


def _track_record(inputs: ReadinessInputs) -> CheckResult:
    months = Decimal(inputs.months_of_history)
    plural = "" if inputs.months_of_history == 1 else "s"
    return _result(
        "track_record",
        _grade(_SPECS_BY_KEY["track_record"], months),
        months,
        f"{inputs.months_of_history} month{plural} of financial history on record.",
    )


def _runway(inputs: ReadinessInputs) -> CheckResult:
    if inputs.runway_months is not None:
        return _result(
            "runway",
            _grade(_SPECS_BY_KEY["runway"], inputs.runway_months),
            inputs.runway_months,
            f"{_months(inputs.runway_months)} months of runway at the current "
            "burn rate.",
        )
    if inputs.is_burning:
        # Burning with nothing left to burn: the engine leaves runway undefined
        # because the division is meaningless, but the finding is the worst one
        # on this list, not an absent one.
        return _result(
            "runway",
            "gap",
            None,
            "Cash is being consumed and the recorded cash balance is at or "
            "below zero, so there is no runway to measure.",
        )
    return _result(
        "runway",
        "ready",
        None,
        "The period generated cash rather than consuming it, so runway is not "
        "the binding constraint.",
    )


def _revenue_growth(inputs: ReadinessInputs) -> CheckResult:
    growth = inputs.revenue_growth_pct
    if growth is None:
        return _result(
            "revenue_growth",
            "not_applicable",
            None,
            "No revenue is recorded in the preceding period, so there is "
            "nothing to measure growth against.",
        )
    direction = "grew" if growth >= ZERO else "fell"
    return _result(
        "revenue_growth",
        _grade(_SPECS_BY_KEY["revenue_growth"], growth),
        growth,
        f"Revenue {direction} {_pct(abs(growth))}% against the preceding "
        "period of equal length.",
    )


def _operating_margin(inputs: ReadinessInputs) -> CheckResult:
    margin = inputs.operating_margin_pct
    if margin is None:
        return _result(
            "operating_margin",
            "not_applicable",
            None,
            "No revenue is recorded in the period, so margin is undefined.",
        )
    detail = (
        f"{_pct(margin)}% of revenue is left after all recorded expenses."
        if margin >= ZERO
        else f"Expenses exceed revenue by {_pct(abs(margin))}% of revenue."
    )
    return _result(
        "operating_margin",
        _grade(_SPECS_BY_KEY["operating_margin"], margin),
        margin,
        detail,
    )


def _revenue_consistency(inputs: ReadinessInputs) -> CheckResult:
    if inputs.months_of_history <= 0:
        return _result(
            "revenue_consistency",
            "not_applicable",
            None,
            "No months of history to measure consistency over.",
        )
    share = _ratio(
        Decimal(inputs.months_with_revenue) * 100,
        Decimal(inputs.months_of_history),
    )
    return _result(
        "revenue_consistency",
        _grade(_SPECS_BY_KEY["revenue_consistency"], share),
        share,
        f"Revenue was recorded in {inputs.months_with_revenue} of the "
        f"{inputs.months_of_history} months on record.",
    )


def _categorized_spend(inputs: ReadinessInputs) -> CheckResult:
    share = inputs.categorized_expense_pct
    if share is None:
        return _result(
            "categorized_spend",
            "not_applicable",
            None,
            "No expenses are recorded in the period.",
        )
    detail = (
        "Every rupee of recorded expense is assigned to a category."
        if share >= Decimal("100")
        else (
            f"{_pct(share)}% of expense value is assigned to a category — the "
            "rest can't be explained to a reader."
        )
    )
    return _result(
        "categorized_spend",
        _grade(_SPECS_BY_KEY["categorized_spend"], share),
        share,
        detail,
    )


def evaluate_readiness(inputs: ReadinessInputs) -> list[CheckResult]:
    """Grade every check, in `CHECK_SPECS` order. Deterministic and total — a
    check that can't be measured comes back `not_applicable`, never missing, so
    the list is the same length on every company."""
    return [
        _track_record(inputs),
        _runway(inputs),
        _revenue_growth(inputs),
        _operating_margin(inputs),
        _revenue_consistency(inputs),
        _categorized_spend(inputs),
    ]


def overall_status(checks: list[CheckResult]) -> CheckStatus:
    """The weakest link — the worst status present, ignoring checks that
    couldn't be measured.

    Not an average and not a score: one four-month runway is not offset by a
    healthy margin, and a company where nothing could be measured is
    `not_applicable`, not `ready`."""
    present = {check.status for check in checks}
    for status in _SEVERITY:
        if status in present:
            return status
    return "not_applicable"


__all__ = [
    "CHECK_SPECS",
    "MONTHS_PER_YEAR",
    "CheckResult",
    "CheckSpec",
    "CheckStatus",
    "ReadinessInputs",
    "annualised_run_rate",
    "burn_multiple",
    "evaluate_readiness",
    "months_of_history",
    "overall_status",
]
