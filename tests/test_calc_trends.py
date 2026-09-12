"""Adjacent-period YoY only, with economic sense assigned in Python. Spec 7.3."""

from decimal import Decimal

from fincopilot.calc.ratios import RATIO_CONTEXT, calculate_metrics
from fincopilot.calc.trends import calculate_trends, yoy
from fincopilot.types import (
    AnalyticalConfidence,
    Direction,
    EconomicSense,
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    NormalizedCell,
    Period,
    Scale,
    ScaleSource,
    UnavailableReason,
    is_unavailable,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref

P24, P23, P22 = Period(2024, "2024"), Period(2023, "2023"), Period(2022, "2022")


def _fv(concept, period, value, row=0):
    cell = NormalizedCell(
        ref=make_source_ref(page=1, row_idx=row, row_label=concept.value),
        raw_token=value,
        value=Decimal(value),
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
    )
    return FinancialValue.from_cell(
        concept=concept,
        period=period,
        cell=cell,
        extraction_confidence=ExtractionConfidence.EXACT_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def _trends(*values, periods=(P24, P23, P22)):
    mapped = {v.concept for v in values}
    report = MappingReport(values, {}, tuple(c for c in C if c not in mapped), ())
    return calculate_trends(calculate_metrics(report, periods), periods)


def test_rising_debt_is_up_and_economically_negative():
    t = yoy("total_debt", Decimal("34600000000"), Decimal("37500000000"), P23, P24)
    assert t.direction is Direction.UP
    assert t.economic is EconomicSense.NEGATIVE
    assert t.absolute_change == Decimal("2900000000")
    assert t.relative_change == RATIO_CONTEXT.divide(Decimal("2900000000"), Decimal("34600000000"))


def test_rising_revenue_is_up_and_positive_falling_is_down_and_negative():
    assert yoy("revenue", Decimal(1), Decimal(2), P23, P24).economic is EconomicSense.POSITIVE
    down = yoy("revenue", Decimal(2), Decimal(1), P23, P24)
    assert down.direction is Direction.DOWN and down.economic is EconomicSense.NEGATIVE


def test_flat_is_neutral():
    t = yoy("revenue", Decimal(5), Decimal(5), P23, P24)
    assert t.direction is Direction.FLAT and t.economic is EconomicSense.NEUTRAL


def test_zero_prior_makes_relative_change_unavailable_not_inf():
    t = yoy("revenue", Decimal(0), Decimal(5), P23, P24)
    assert is_unavailable(t.relative_change)
    assert t.relative_change.reason is UnavailableReason.DIVISION_BY_ZERO
    assert t.direction is Direction.UP


def test_only_adjacent_periods_are_compared():
    ts = _trends(_fv(C.REVENUE, P24, "3"), _fv(C.REVENUE, P23, "2"), _fv(C.REVENUE, P22, "1"))
    pairs = {(t.from_period.end_year, t.to_period.end_year) for t in ts.trends}
    assert pairs == {(2023, 2024), (2022, 2023)}


def test_missing_period_value_yields_unavailable_trend_with_cause():
    ts = _trends(_fv(C.REVENUE, P24, "3"), periods=(P24, P23))
    t = ts.get("revenue", P24)
    assert is_unavailable(t)
    assert t.root().reason is UnavailableReason.MISSING_INPUT


def test_metric_trends_use_metric_values():
    ts = _trends(
        _fv(C.TOTAL_DEBT, P24, "200", row=0),
        _fv(C.EQUITY, P24, "100", row=1),
        _fv(C.TOTAL_DEBT, P23, "100", row=0),
        _fv(C.EQUITY, P23, "100", row=1),
        periods=(P24, P23),
    )
    t = ts.get("debt_to_equity", P24)
    assert t.absolute_change == Decimal(1)
    assert t.direction is Direction.UP and t.economic is EconomicSense.NEGATIVE
