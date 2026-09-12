"""Each rule fires and does not fire on constructed inputs; not_evaluated carries
its reason. Spec 7.5."""

from decimal import Decimal

from fincopilot.calc.ratios import calculate_metrics
from fincopilot.calc.reconcile import run_reconciliations
from fincopilot.calc.trends import calculate_trends
from fincopilot.rules.redflags import RULES, evaluate_red_flags
from fincopilot.types import (
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    NormalizedCell,
    Period,
    RuleOutcome,
    Scale,
    ScaleSource,
    Severity,
    UnavailableReason,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref

P24, P23 = Period(2024, "2024"), Period(2023, "2023")


def _fv(concept, period, value, row=0, llm=False):
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
        extraction_confidence=ExtractionConfidence.LLM_MAPPED
        if llm
        else ExtractionConfidence.EXACT_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def _flags(*values):
    mapped = {v.concept for v in values}
    report = MappingReport(values, {}, tuple(c for c in C if c not in mapped), ())
    periods = (P24, P23)
    ms = calculate_metrics(report, periods)
    ts = calculate_trends(ms, periods)
    rr = run_reconciliations(ms, periods)
    return {f.rule_id: f for f in evaluate_red_flags(ms, ts, rr, report, periods)}


def _both(concept, v24, v23, row):
    return (_fv(concept, P24, v24, row), _fv(concept, P23, v23, row))


def test_every_rule_is_reported_exactly_once():
    flags = _flags()
    assert set(flags) == {r.rule_id for r in RULES}
    assert len(flags) == 10


def test_unavailable_inputs_are_not_evaluated_with_reason_never_silent_pass():
    f = _flags()["high_leverage"]
    assert f.outcome is RuleOutcome.NOT_EVALUATED
    assert f.reason is not None
    assert f.reason.root().reason is UnavailableReason.MISSING_INPUT


def test_revenue_decline_fires_and_clears():
    assert _flags(*_both(C.REVENUE, "90", "100", 0))["revenue_decline"].outcome is RuleOutcome.FIRED
    assert (
        _flags(*_both(C.REVENUE, "110", "100", 0))["revenue_decline"].outcome is RuleOutcome.CLEAR
    )


def test_margin_compression_fires_on_operating_margin_alone():
    flags = _flags(*_both(C.REVENUE, "100", "100", 0), *_both(C.OPERATING_INCOME, "10", "13", 1))
    assert flags["margin_compression"].outcome is RuleOutcome.FIRED  # 13% -> 10%
    flags = _flags(*_both(C.REVENUE, "100", "100", 0), *_both(C.OPERATING_INCOME, "12", "13", 1))
    assert flags["margin_compression"].outcome is RuleOutcome.CLEAR  # 100 bps only


def test_leverage_increase_needs_both_delta_and_floor():
    # 0.1 -> 0.4: delta 0.3 but below the 1.0 floor. Deliberately suppressed.
    flags = _flags(*_both(C.TOTAL_DEBT, "40", "10", 0), *_both(C.EQUITY, "100", "100", 1))
    assert flags["leverage_increase"].outcome is RuleOutcome.CLEAR
    # 1.0 -> 1.3: fires.
    flags = _flags(*_both(C.TOTAL_DEBT, "130", "100", 0), *_both(C.EQUITY, "100", "100", 1))
    assert flags["leverage_increase"].outcome is RuleOutcome.FIRED
    # 1.5 -> 1.6: above floor but delta too small.
    flags = _flags(*_both(C.TOTAL_DEBT, "160", "150", 0), *_both(C.EQUITY, "100", "100", 1))
    assert flags["leverage_increase"].outcome is RuleOutcome.CLEAR


def test_high_leverage_fires_above_two():
    flags = _flags(_fv(C.TOTAL_DEBT, P24, "201", 0), _fv(C.EQUITY, P24, "100", 1))
    f = flags["high_leverage"]
    assert f.outcome is RuleOutcome.FIRED and f.severity is Severity.CRITICAL
    assert f.refs == ("page_1_table_0_row_0", "page_1_table_0_row_1")
    flags = _flags(_fv(C.TOTAL_DEBT, P24, "200", 0), _fv(C.EQUITY, P24, "100", 1))
    assert flags["high_leverage"].outcome is RuleOutcome.CLEAR


def test_negative_equity_makes_leverage_rules_not_evaluated():
    flags = _flags(_fv(C.TOTAL_DEBT, P24, "300", 0), _fv(C.EQUITY, P24, "-50", 1))
    assert flags["high_leverage"].outcome is RuleOutcome.NOT_EVALUATED
    assert flags["high_leverage"].reason.reason is UnavailableReason.AMBIGUOUS


def test_negative_fcf_and_ocf():
    flags = _flags(_fv(C.OPERATING_CASH_FLOW, P24, "-5", 0), _fv(C.CAPEX, P24, "-10", 1))
    assert flags["negative_ocf"].outcome is RuleOutcome.FIRED
    assert flags["negative_fcf"].outcome is RuleOutcome.FIRED
    flags = _flags(_fv(C.OPERATING_CASH_FLOW, P24, "50", 0), _fv(C.CAPEX, P24, "-10", 1))
    assert flags["negative_ocf"].outcome is RuleOutcome.CLEAR
    assert flags["negative_fcf"].outcome is RuleOutcome.CLEAR


def test_weak_liquidity():
    flags = _flags(_fv(C.CURRENT_ASSETS, P24, "99", 0), _fv(C.CURRENT_LIABILITIES, P24, "100", 1))
    assert flags["weak_liquidity"].outcome is RuleOutcome.FIRED
    flags = _flags(_fv(C.CURRENT_ASSETS, P24, "100", 0), _fv(C.CURRENT_LIABILITIES, P24, "100", 1))
    assert flags["weak_liquidity"].outcome is RuleOutcome.CLEAR


def test_earnings_quality_requires_both_positive():
    flags = _flags(_fv(C.OPERATING_CASH_FLOW, P24, "60", 0), _fv(C.NET_INCOME, P24, "100", 1))
    assert flags["earnings_quality"].outcome is RuleOutcome.FIRED
    flags = _flags(_fv(C.OPERATING_CASH_FLOW, P24, "70", 0), _fv(C.NET_INCOME, P24, "100", 1))
    assert flags["earnings_quality"].outcome is RuleOutcome.CLEAR
    # Against a loss the ratio itself is not meaningful (spec 7.1), so the
    # rule reports that it could not check rather than a silent clear.
    flags = _flags(_fv(C.OPERATING_CASH_FLOW, P24, "60", 0), _fv(C.NET_INCOME, P24, "-100", 1))
    assert flags["earnings_quality"].outcome is RuleOutcome.NOT_EVALUATED
    assert flags["earnings_quality"].reason.reason is UnavailableReason.AMBIGUOUS


def test_reconciliation_warning_fires_on_a_warning_and_is_not_evaluated_without_checks():
    flags = _flags(
        _fv(C.TOTAL_ASSETS, P24, "1000", 0),
        _fv(C.TOTAL_LIABILITIES, P24, "500", 1),
        _fv(C.EQUITY, P24, "100", 2),
    )
    assert flags["reconciliation_warning"].outcome is RuleOutcome.FIRED
    assert _flags()["reconciliation_warning"].outcome is RuleOutcome.NOT_EVALUATED


def test_low_confidence_kpi_fires_on_llm_mapped_or_unmapped_headline():
    flags = _flags(_fv(C.REVENUE, P24, "1", 0, llm=True), _fv(C.NET_INCOME, P24, "1", 1))
    assert flags["low_confidence_kpi"].outcome is RuleOutcome.FIRED
    assert _flags(_fv(C.NET_INCOME, P24, "1", 1))["low_confidence_kpi"].outcome is RuleOutcome.FIRED
    flags = _flags(_fv(C.REVENUE, P24, "1", 0), _fv(C.NET_INCOME, P24, "1", 1))
    assert flags["low_confidence_kpi"].outcome is RuleOutcome.CLEAR
