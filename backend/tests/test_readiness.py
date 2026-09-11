"""Unit tests for the investor-readiness rules (task 8.3, FR-7.3) — pure
functions, no DB.

These pin the *judgement* half of the summary: that each check grades against
its stated fixed threshold, that a figure the engine leaves undefined never
grades as a quiet pass, and that the overall status is the weakest link rather
than an average.
"""

import datetime as dt
from decimal import Decimal

from app.financial_engine.readiness import (
    CHECK_SPECS,
    ReadinessInputs,
    annualised_run_rate,
    burn_multiple,
    evaluate_readiness,
    months_of_history,
    overall_status,
)


def _inputs(**overrides) -> ReadinessInputs:
    """A company that passes every check, so each test can fail exactly one."""
    base = dict(
        months_of_history=18,
        months_with_revenue=18,
        runway_months=Decimal("24.00"),
        is_burning=True,
        revenue_growth_pct=Decimal("50.00"),
        operating_margin_pct=Decimal("15.00"),
        categorized_expense_pct=Decimal("100.00"),
    )
    base.update(overrides)
    return ReadinessInputs(**base)


def _by_key(inputs: ReadinessInputs) -> dict:
    return {check.key: check for check in evaluate_readiness(inputs)}


# --- Run rate and burn efficiency ---


def test_run_rate_annualises_the_latest_month():
    """ARR is the current month × 12, not the trailing year averaged — a
    run-rate answers "what is this earning now"."""
    assert annualised_run_rate(Decimal("200000")) == Decimal("2400000.00")


def test_burn_multiple_is_burn_per_rupee_of_new_revenue():
    # Burned 10L to add 5L of annual revenue → 2.0x.
    assert burn_multiple(
        Decimal("1000000"), Decimal("1500000"), Decimal("1000000")
    ) == Decimal("2.00")


def test_burn_multiple_is_undefined_when_not_burning():
    """A profitable period has no burn to divide — 0 would read as perfect
    efficiency, which is a different claim."""
    assert (
        burn_multiple(Decimal("-50000"), Decimal("1500000"), Decimal("1000000"))
        is None
    )


def test_burn_multiple_is_undefined_when_revenue_did_not_grow():
    """Dividing by zero or negative new revenue produces a number that looks
    like efficiency and isn't."""
    assert burn_multiple(Decimal("500000"), Decimal("900000"), Decimal("1000000")) is None
    assert burn_multiple(Decimal("500000"), Decimal("1000000"), Decimal("1000000")) is None


def test_months_of_history_counts_calendar_months_inclusively():
    assert months_of_history(dt.date(2026, 1, 1), dt.date(2026, 12, 31)) == 12
    assert months_of_history(dt.date(2026, 7, 15), dt.date(2026, 7, 20)) == 1


# --- The checklist ---


def test_every_spec_is_graded_exactly_once_and_in_order():
    """Total by construction: the same list, same length, on every company —
    a check that can't be measured comes back not_applicable, never missing."""
    checks = evaluate_readiness(_inputs())
    assert [c.key for c in checks] == [s.key for s in CHECK_SPECS]


def test_a_healthy_company_is_ready_on_every_check():
    checks = evaluate_readiness(_inputs())
    assert {c.status for c in checks} == {"ready"}
    assert overall_status(checks) == "ready"


def test_thresholds_are_inclusive_at_the_ready_boundary():
    """Exactly 12 months of runway is ready, a hair under is attention — the
    rule the summary prints is the rule it applies."""
    assert _by_key(_inputs(runway_months=Decimal("12.00")))["runway"].status == "ready"
    assert (
        _by_key(_inputs(runway_months=Decimal("11.99")))["runway"].status == "attention"
    )
    assert _by_key(_inputs(runway_months=Decimal("5.99")))["runway"].status == "gap"


def test_track_record_grades_months_on_record():
    assert _by_key(_inputs(months_of_history=12))["track_record"].status == "ready"
    assert _by_key(_inputs(months_of_history=7))["track_record"].status == "attention"
    assert _by_key(_inputs(months_of_history=3))["track_record"].status == "gap"


def test_growth_and_margin_grade_against_their_thresholds():
    assert (
        _by_key(_inputs(revenue_growth_pct=Decimal("5")))["revenue_growth"].status
        == "attention"
    )
    assert (
        _by_key(_inputs(revenue_growth_pct=Decimal("-8")))["revenue_growth"].status
        == "gap"
    )
    assert (
        _by_key(_inputs(operating_margin_pct=Decimal("-20")))[
            "operating_margin"
        ].status
        == "attention"
    )
    assert (
        _by_key(_inputs(operating_margin_pct=Decimal("-80")))[
            "operating_margin"
        ].status
        == "gap"
    )


def test_revenue_consistency_is_a_share_of_the_months_on_record():
    """Measured over the company's own history, so a young company isn't marked
    inconsistent for the months before it existed."""
    check = _by_key(_inputs(months_of_history=8, months_with_revenue=8))[
        "revenue_consistency"
    ]
    assert check.value == Decimal("100.00")
    assert check.status == "ready"

    patchy = _by_key(_inputs(months_of_history=12, months_with_revenue=6))[
        "revenue_consistency"
    ]
    assert patchy.value == Decimal("50.00")
    assert patchy.status == "gap"


def test_uncategorized_spend_is_graded_by_value():
    check = _by_key(_inputs(categorized_expense_pct=Decimal("85.00")))[
        "categorized_spend"
    ]
    assert check.status == "attention"
    assert "85%" in check.detail


# --- Undefined figures ---


def test_profitable_company_with_no_runway_figure_is_ready_not_missing():
    """The engine leaves runway null when a company isn't burning. That's the
    best possible answer to "how long do you survive", not an absent one."""
    check = _by_key(_inputs(runway_months=None, is_burning=False))["runway"]
    assert check.status == "ready"
    assert check.value is None
    assert "generated cash" in check.detail


def test_burning_with_no_cash_left_is_the_worst_finding_not_an_absent_one():
    check = _by_key(_inputs(runway_months=None, is_burning=True))["runway"]
    assert check.status == "gap"
    assert check.value is None


def test_unmeasurable_checks_are_not_applicable_never_a_quiet_pass():
    checks = _by_key(
        _inputs(
            revenue_growth_pct=None,
            operating_margin_pct=None,
            categorized_expense_pct=None,
        )
    )
    for key in ("revenue_growth", "operating_margin", "categorized_spend"):
        assert checks[key].status == "not_applicable", key
        assert checks[key].value is None


# --- Overall status ---


def test_overall_status_is_the_weakest_link_not_an_average():
    """Five readys and one four-month runway is not a ready company."""
    checks = evaluate_readiness(_inputs(runway_months=Decimal("4.00")))
    assert [c.status for c in checks].count("ready") == 5
    assert overall_status(checks) == "gap"


def test_attention_surfaces_when_nothing_is_an_outright_gap():
    checks = evaluate_readiness(_inputs(revenue_growth_pct=Decimal("3")))
    assert overall_status(checks) == "attention"


def test_unmeasurable_checks_do_not_drag_the_overall_status_down():
    """A check that couldn't be measured is not a finding — but a company where
    nothing could be measured isn't 'ready' either."""
    measured = evaluate_readiness(_inputs(revenue_growth_pct=None))
    assert overall_status(measured) == "ready"

    nothing = [
        c
        for c in evaluate_readiness(
            ReadinessInputs(
                months_of_history=0,
                months_with_revenue=0,
                runway_months=None,
                is_burning=False,
                revenue_growth_pct=None,
                operating_margin_pct=None,
                categorized_expense_pct=None,
            )
        )
        if c.status == "not_applicable"
    ]
    assert overall_status(nothing) == "not_applicable"


def test_detail_text_states_the_measured_figure():
    """The prose is a template filled with the graded figure, so it can never
    disagree with `value` — and no LLM writes it."""
    checks = _by_key(_inputs(months_of_history=9, revenue_growth_pct=Decimal("-12.5")))
    assert checks["track_record"].detail == "9 months of financial history on record."
    assert "fell 12.5%" in checks["revenue_growth"].detail


def test_fully_categorized_spend_does_not_talk_about_a_remainder():
    """At 100% there is no "rest" — the sentence has to stop being a template
    the moment the template stops being true."""
    detail = _by_key(_inputs(categorized_expense_pct=Decimal("100.00")))[
        "categorized_spend"
    ].detail
    assert detail == "Every rupee of recorded expense is assigned to a category."
