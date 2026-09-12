"""Every formula, every guard, Decimal precision at crore scale. Spec 7.1, 7.2."""

import json
from decimal import Decimal
from pathlib import Path

import pytest

from fincopilot.calc.ratios import (
    RATIO_CONTEXT,
    calculate_metrics,
    derive_ebitda,
    derive_free_cash_flow,
    derive_total_debt,
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
    Scale,
    ScaleSource,
    UnavailableReason,
    is_unavailable,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref

FIXTURES = Path(__file__).parent / "fixtures"
P24, P23 = Period(2024, "2024"), Period(2023, "2023")


def _fv(concept: C, period: Period, value: str, *, row: int = 0, llm: bool = False):
    cell = NormalizedCell(
        ref=make_source_ref(page=1, row_idx=row, row_label=concept.value),
        raw_token=value,
        value=Decimal(value),
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
    )
    conf = ExtractionConfidence.LLM_MAPPED if llm else ExtractionConfidence.EXACT_MATCH
    return FinancialValue.from_cell(
        concept=concept,
        period=period,
        cell=cell,
        extraction_confidence=conf,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def _report(*values: FinancialValue) -> MappingReport:
    mapped = {v.concept for v in values}
    return MappingReport(
        values=values,
        unavailable={},
        unmapped=tuple(c for c in C if c not in mapped),
        conflicts=(),
    )


# --- derived values: strict pattern


def test_total_debt_direct_mapping_wins_over_derivation():
    r = _report(
        _fv(C.TOTAL_DEBT, P24, "100", row=0),
        _fv(C.SHORT_TERM_BORROWINGS, P24, "1", row=1),
        _fv(C.LONG_TERM_BORROWINGS, P24, "2", row=2),
    )
    td = derive_total_debt(r, P24)
    assert td.value == Decimal("100") and td.derived_from is None


def test_total_debt_derives_only_when_both_inputs_exist():
    r = _report(
        _fv(C.SHORT_TERM_BORROWINGS, P24, "9000000000", row=1),
        _fv(C.LONG_TERM_BORROWINGS, P24, "28500000000", row=2),
    )
    td = derive_total_debt(r, P24)
    assert td.value == Decimal("37500000000")
    assert td.derived_from == ("short_term_borrowings", "long_term_borrowings")
    assert td.cell is None


def test_total_debt_never_half_sums():
    r = _report(_fv(C.SHORT_TERM_BORROWINGS, P24, "900", row=1))
    td = derive_total_debt(r, P24)
    assert is_unavailable(td) and td.reason is UnavailableReason.MISSING_INPUT
    assert "long_term_borrowings" in td.detail


def test_fcf_normalises_capex_magnitude_first():
    r = _report(_fv(C.OPERATING_CASH_FLOW, P24, "2180", row=0), _fv(C.CAPEX, P24, "-1240", row=1))
    fcf = derive_free_cash_flow(r, P24)
    assert fcf.value == Decimal("940")
    r2 = _report(_fv(C.OPERATING_CASH_FLOW, P24, "2180", row=0), _fv(C.CAPEX, P24, "1240", row=1))
    assert derive_free_cash_flow(r2, P24).value == Decimal("940")


def test_ebitda_derived_and_carries_lowest_input_confidence():
    r = _report(
        _fv(C.OPERATING_INCOME, P24, "1940.50", row=0),
        _fv(C.D_AND_A, P24, "640", row=1, llm=True),
    )
    e = derive_ebitda(r, P24)
    assert e.value == Decimal("2580.50")
    assert e.derived_from == ("operating_income", "d_and_a")
    assert e.analytical_confidence is AnalyticalConfidence.MEDIUM


def test_ebitda_without_d_and_a_is_unavailable_never_fabricated():
    r = _report(_fv(C.OPERATING_INCOME, P24, "1940.50"))
    assert is_unavailable(derive_ebitda(r, P24))


# --- guards


def _metrics(*values):
    return calculate_metrics(_report(*values), (P24, P23))


def test_zero_denominator_is_division_by_zero_never_inf():
    ms = _metrics(
        _fv(C.CURRENT_ASSETS, P24, "10", row=0), _fv(C.CURRENT_LIABILITIES, P24, "0", row=1)
    )
    m = ms.metric("current_ratio", P24)
    assert is_unavailable(m) and m.reason is UnavailableReason.DIVISION_BY_ZERO
    assert m.refs == ("page_1_table_0_row_1",)


def test_negative_equity_makes_debt_to_equity_ambiguous():
    ms = _metrics(_fv(C.TOTAL_DEBT, P24, "3520", row=0), _fv(C.EQUITY, P24, "-820", row=1))
    m = ms.metric("debt_to_equity", P24)
    assert is_unavailable(m) and m.reason is UnavailableReason.AMBIGUOUS


def test_zero_or_negative_revenue_kills_margins():
    for rev in ("0", "-5"):
        ms = _metrics(_fv(C.REVENUE, P24, rev, row=0), _fv(C.NET_INCOME, P24, "1", row=1))
        assert is_unavailable(ms.metric("net_margin", P24))


def test_roa_and_roe_need_two_periods_never_one():
    ms = _metrics(
        _fv(C.NET_INCOME, P24, "643", row=0),
        _fv(C.TOTAL_ASSETS, P24, "7590", row=1),
        _fv(C.EQUITY, P24, "4440", row=2),
    )
    roa = ms.metric("roa", P24)
    assert is_unavailable(roa) and "prior-period" in roa.detail
    assert is_unavailable(ms.metric("roe", P24))


def test_roa_uses_the_average_of_two_balance_sheets():
    ms = _metrics(
        _fv(C.NET_INCOME, P24, "643", row=0),
        _fv(C.TOTAL_ASSETS, P24, "7590", row=1),
        _fv(C.TOTAL_ASSETS, P23, "6950", row=1),
    )
    roa = ms.metric("roa", P24)
    assert roa.value == RATIO_CONTEXT.divide(Decimal("643"), Decimal("7270"))
    assert roa.inputs[0] == "page_1_table_0_row_0"


def test_unavailable_input_propagates_with_root_cause():
    ms = _metrics(_fv(C.NET_INCOME, P24, "1"))
    m = ms.metric("net_margin", P24)
    assert is_unavailable(m)
    assert m.root().reason is UnavailableReason.MISSING_INPUT
    assert "revenue" in m.root().detail


# --- goldens: derived values exact, ratios exact under RATIO_CONTEXT


def _golden(name):
    data = (FIXTURES / f"{name}.pdf").read_bytes()
    doc = extract_pdf(data, validate_input(data))
    statements = locate_statements(doc)
    periods = detect_periods(statements)
    normalized = normalize_document(statements, periods, doc)
    report = validate_mappings(map_rows(normalized), normalized, periods)
    expected = json.loads((FIXTURES / "expected" / f"{name}.json").read_text(encoding="utf-8"))
    return calculate_metrics(report, periods.ordered), expected


@pytest.mark.parametrize("name", ["golden_indian", "golden_us"])
def test_golden_derived_values_match_hand_computed_sums(name):
    ms, expected = _golden(name)
    for concept, spec in expected["derived"].items():
        for year, base in spec.items():
            if not year.isdigit():
                continue
            v = ms.value(C(concept), Period(int(year), year))
            assert isinstance(v, FinancialValue), (concept, year, v)
            assert v.value == Decimal(base), (concept, year)
            assert v.derived_from == tuple(spec["from"])


def test_golden_us_ratios_are_exact_under_the_declared_context():
    ms, e = _golden("golden_us")
    m = e["mapped"]
    div = RATIO_CONTEXT.divide

    def d(k, y):
        return Decimal(m[k][y])

    assert ms.metric("gross_margin", P24).value == div(
        d("gross_profit", "2024"), d("revenue", "2024")
    )
    assert ms.metric("current_ratio", P24).value == div(
        d("current_assets", "2024"), d("current_liabilities", "2024")
    )
    assert ms.metric("debt_to_equity", P24).value == div(
        Decimal(e["derived"]["total_debt"]["2024"]), d("equity", "2024")
    )
    avg_assets = div(d("total_assets", "2024") + d("total_assets", "2023"), Decimal(2))
    assert ms.metric("roa", P24).value == div(d("net_income", "2024"), avg_assets)
    assert is_unavailable(ms.metric("roa", Period(2022, "2022")))
    assert is_unavailable(ms.value(C.TOTAL_DEBT, Period(2022, "2022")))


def test_golden_indian_gross_margin_is_unavailable_with_reason():
    ms, _ = _golden("golden_indian")
    gm = ms.metric("gross_margin", P24)
    assert is_unavailable(gm) and gm.root().reason is UnavailableReason.MISSING_INPUT
    assert ms.metric("net_margin", P24).value == RATIO_CONTEXT.divide(
        Decimal("12455000000"), Decimal("124500000000")
    )
