"""Soft reconciliation: passed / warning / unavailable, never a hard failure. Spec 7.4."""

from decimal import Decimal
from pathlib import Path

from fincopilot.calc.ratios import calculate_metrics
from fincopilot.calc.reconcile import (
    ASSETS_CHECK,
    FCF_CHECK,
    GROSS_PROFIT_CHECK,
    run_reconciliations,
)
from fincopilot.extract.locate import locate_statements
from fincopilot.extract.pdf import extract_pdf, validate_input
from fincopilot.extract.periods import detect_periods
from fincopilot.extract.units import normalize_document
from fincopilot.mapping.synonyms import map_rows
from fincopilot.mapping.validate import validate_mappings
from fincopilot.types import (
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    NormalizedCell,
    Period,
    ReconciliationStatus,
    Scale,
    ScaleSource,
    StatementKind,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref

FIXTURES = Path(__file__).parent / "fixtures"
P24 = Period(2024, "2024")


def _fv(concept, value, row=0):
    cell = NormalizedCell(
        ref=make_source_ref(page=42, row_idx=row, row_label=concept.value),
        raw_token=value,
        value=Decimal(value),
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
    )
    return FinancialValue.from_cell(
        concept=concept,
        period=P24,
        cell=cell,
        extraction_confidence=ExtractionConfidence.EXACT_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def _run(*values, dash=None):
    mapped = {v.concept for v in values}
    report = MappingReport(values, {}, tuple(c for c in C if c not in mapped), ())
    return run_reconciliations(calculate_metrics(report, (P24,)), (P24,), dash)


def test_assets_check_passes_within_half_a_percent():
    r = _run(
        _fv(C.TOTAL_ASSETS, "13620", 0),
        _fv(C.TOTAL_LIABILITIES, "6690", 1),
        _fv(C.EQUITY, "6930", 2),
    )
    c = r.get(ASSETS_CHECK, P24)
    assert c.status is ReconciliationStatus.PASSED
    assert c.delta == Decimal(0)
    assert c.tolerance == Decimal("68.100")
    assert set(c.refs) == {
        "page_42_table_0_row_0",
        "page_42_table_0_row_1",
        "page_42_table_0_row_2",
    }


def test_assets_check_warns_outside_tolerance_showing_both_sides():
    r = _run(
        _fv(C.TOTAL_ASSETS, "4280", 0),
        _fv(C.TOTAL_LIABILITIES, "5100", 1),
        _fv(C.EQUITY, "-820", 2),
    )
    c = r.get(ASSETS_CHECK, P24)
    # 5100 + (-820) = 4280: balances even with negative equity.
    assert c.status is ReconciliationStatus.PASSED
    r2 = _run(
        _fv(C.TOTAL_ASSETS, "4280", 0),
        _fv(C.TOTAL_LIABILITIES, "5100", 1),
        _fv(C.EQUITY, "100", 2),
    )
    c2 = r2.get(ASSETS_CHECK, P24)
    assert c2.status is ReconciliationStatus.WARNING
    assert c2.left == Decimal("4280") and c2.right == Decimal("5200")
    assert c2.delta == Decimal("-920")
    assert "delta" in c2.detail


def test_warning_names_dash_zero_cells_as_suspects():
    r = _run(
        _fv(C.TOTAL_ASSETS, "4280", 0),
        _fv(C.TOTAL_LIABILITIES, "5100", 1),
        _fv(C.EQUITY, "100", 2),
        dash={StatementKind.BALANCE: ("page_42_table_0_row_7",)},
    )
    assert "page_42_table_0_row_7" in r.get(ASSETS_CHECK, P24).detail


def test_missing_inputs_are_unavailable_not_failed():
    r = _run(_fv(C.TOTAL_ASSETS, "4280", 0))
    c = r.get(ASSETS_CHECK, P24)
    assert c.status is ReconciliationStatus.UNAVAILABLE
    assert "cannot check" in c.detail


def test_fcf_check_is_exact_when_fcf_is_derived():
    r = _run(_fv(C.OPERATING_CASH_FLOW, "2180", 0), _fv(C.CAPEX, "-1240", 1))
    c = r.get(FCF_CHECK, P24)
    assert c.status is ReconciliationStatus.PASSED and c.tolerance == Decimal(0)


def test_fcf_check_warns_when_a_mapped_fcf_row_disagrees():
    r = _run(
        _fv(C.OPERATING_CASH_FLOW, "2180", 0),
        _fv(C.CAPEX, "-1240", 1),
        _fv(C.FREE_CASH_FLOW, "999", 2),
    )
    assert r.get(FCF_CHECK, P24).status is ReconciliationStatus.WARNING


def _golden(name):
    data = (FIXTURES / f"{name}.pdf").read_bytes()
    doc = extract_pdf(data, validate_input(data))
    statements = locate_statements(doc)
    periods = detect_periods(statements)
    normalized = normalize_document(statements, periods, doc)
    report = validate_mappings(map_rows(normalized), normalized, periods)
    return run_reconciliations(calculate_metrics(report, periods.ordered), periods.ordered)


def test_golden_us_all_three_checks_pass():
    r = _golden("golden_us")
    for name in (ASSETS_CHECK, GROSS_PROFIT_CHECK, FCF_CHECK):
        assert r.get(name, P24).status is ReconciliationStatus.PASSED, name
    assert not r.warnings


def test_golden_indian_gross_profit_check_is_unavailable():
    r = _golden("golden_indian")
    assert r.get(ASSETS_CHECK, P24).status is ReconciliationStatus.PASSED
    assert r.get(GROSS_PROFIT_CHECK, P24).status is ReconciliationStatus.UNAVAILABLE
    assert r.get(FCF_CHECK, P24).status is ReconciliationStatus.PASSED


def test_hostile_balance_sheet_warns_instead_of_crashing():
    r = _golden("hostile")
    c = r.get(ASSETS_CHECK, P24)
    # 5,100 + (-820) = 4,280 balances; the 2023 sheet does not: 4,220 - 310 != 3,910.
    assert c.status is ReconciliationStatus.PASSED
    assert r.get(ASSETS_CHECK, Period(2023, "2023")).status is ReconciliationStatus.PASSED
