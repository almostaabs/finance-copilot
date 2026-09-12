from decimal import Decimal

from fincopilot.types import (
    AnalyticalConfidence,
    Direction,
    EconomicSense,
    Metric,
    MetricUnit,
    Period,
    ReconciliationCheck,
    ReconciliationStatus,
    RedFlag,
    RuleOutcome,
    Severity,
    Trend,
    Unavailable,
    UnavailableReason,
    is_unavailable,
)

FY2024 = Period(2024, "FY2024")
FY2023 = Period(2023, "FY2023")


def test_metric_names_the_inputs_it_was_computed_from():
    m = Metric(
        name="current_ratio",
        period=FY2024,
        value=Decimal("1.765625"),
        unit=MetricUnit.RATIO,
        inputs=("page_42_table_0_row_7", "page_42_table_0_row_18"),
        analytical_confidence=AnalyticalConfidence.HIGH,
    )
    assert m.inputs == ("page_42_table_0_row_7", "page_42_table_0_row_18")
    assert m.unit is MetricUnit.RATIO


def test_trend_carries_economic_sense_separately_from_direction():
    # Rising debt is "up" and economically negative. The Phase 9 narrative model
    # is handed this label and never derives it, so it cannot describe rising
    # leverage as "strong balance-sheet growth".
    t = Trend(
        subject="total_debt",
        from_period=FY2023,
        to_period=FY2024,
        absolute_change=Decimal("2900000000"),
        relative_change=Decimal("0.0838150289"),
        direction=Direction.UP,
        economic=EconomicSense.NEGATIVE,
    )
    assert t.direction is Direction.UP
    assert t.economic is EconomicSense.NEGATIVE


def test_trend_relative_change_may_be_unavailable():
    t = Trend(
        subject="revenue",
        from_period=FY2023,
        to_period=FY2024,
        absolute_change=Decimal("1000"),
        relative_change=Unavailable(UnavailableReason.DIVISION_BY_ZERO, "prior revenue is zero"),
        direction=Direction.UP,
        economic=EconomicSense.POSITIVE,
    )
    assert is_unavailable(t.relative_change)


def test_reconciliation_shows_both_sides_and_the_delta():
    check = ReconciliationCheck(
        name="assets_equal_liabilities_plus_equity",
        period=FY2024,
        status=ReconciliationStatus.PASSED,
        left=Decimal("136200000000"),
        right=Decimal("136200000000"),
        delta=Decimal(0),
        tolerance=Decimal("681000000"),  # 0.5% of total assets
        detail="13,620.00 = 6,690.00 + 6,930.00",
        refs=("page_42_table_0_row_8",),
    )
    assert check.status is ReconciliationStatus.PASSED
    assert check.delta == Decimal(0)


def test_reconciliation_status_is_soft_with_no_hard_failure_state():
    assert {s.value for s in ReconciliationStatus} == {"passed", "warning", "unavailable"}


def test_red_flag_that_could_not_be_evaluated_says_why():
    reason = Unavailable(UnavailableReason.MISSING_INPUT, "equity unmapped")
    flag = RedFlag(
        rule_id="high_leverage",
        outcome=RuleOutcome.NOT_EVALUATED,
        severity=Severity.WARNING,
        message="Leverage could not be assessed.",
        refs=(),
        reason=reason,
    )
    assert flag.outcome is RuleOutcome.NOT_EVALUATED
    assert flag.reason is reason


def test_rule_outcome_distinguishes_clear_from_not_evaluated():
    # "checked, clean" and "could not check" must never look the same.
    assert {o.value for o in RuleOutcome} == {"fired", "clear", "not_evaluated"}
