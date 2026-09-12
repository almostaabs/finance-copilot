"""Regression tests for the stress-test findings in docs/KNOWN_ISSUES.md."""

from decimal import Decimal
from pathlib import Path

import pipeline
import pytest

from fincopilot.ai.llm_map import validate_response
from fincopilot.calc.ratios import calculate_metrics, derive_total_debt
from fincopilot.extract.periods import parse_period
from fincopilot.extract.units import normalized_cell, parse_number
from fincopilot.types import (
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    NormalizedCell,
    Period,
    Scale,
    ScaleSource,
    TableRow,
    UnavailableReason,
    is_unavailable,
)
from fincopilot.types import CanonicalConcept as C
from tests.helpers import make_source_ref

FIXTURES = Path(__file__).parent / "fixtures"
P24, P23 = Period(2024, "2024"), Period(2023, "2023")


# --- 1: malformed model output must never crash the pipeline


class NestedBomb:
    def complete_json(self, prompt, schema):
        return "[" * 5000 + "]" * 5000


class HugeBlob:
    def complete_json(self, prompt, schema):
        return '{"source_row_id": "' + "a" * 5_000_000 + '"}'


@pytest.mark.parametrize("client", [NestedBomb(), HugeBlob()])
def test_garbage_model_output_leaves_pipeline_intact(client):
    data = (FIXTURES / "golden_indian.pdf").read_bytes()
    result = pipeline.analyze(data, llm=client)
    assert result.metric_set.value(C.REVENUE, P24).value == Decimal("124500000000")
    assert C.GROSS_PROFIT in result.mapping.unmapped


def test_deep_nesting_is_rejected_not_raised():
    r = validate_response(
        "[" * 5000 + "]" * 5000,
        concept=C.GROSS_PROFIT,
        candidate_ids=set(),
        refs={},
        already_mapped={},
    )
    assert is_unavailable(r) and r.reason is UnavailableReason.UNPARSEABLE


# --- 6: duplicate keys must be rejected, not resolved last-wins


def test_duplicate_json_keys_are_rejected():
    ref = make_source_ref(page=1, row_idx=0)
    raw = '{"source_row_id": null, "source_row_id": "page_1_table_0_row_0"}'
    r = validate_response(
        raw,
        concept=C.GROSS_PROFIT,
        candidate_ids={"page_1_table_0_row_0"},
        refs={"page_1_table_0_row_0": ref},
        already_mapped={},
    )
    assert is_unavailable(r) and r.reason is UnavailableReason.UNPARSEABLE


# --- 3: only ASCII digits belong to the grammars


@pytest.mark.parametrize(
    "token",
    ["\u0966\u0967\u0968", "\u0661\u0662\u0663", "\u0967\u0968,\u096a\u096b\u0966.\u0966\u0966"],
)
def test_non_ascii_numerals_are_unparseable(token):
    r = parse_number(token)
    assert is_unavailable(r) and r.reason is UnavailableReason.UNPARSEABLE


def test_non_ascii_digits_never_form_a_year():
    assert is_unavailable(parse_period("\u0968\u0966\u0968\u096a"))


# --- 5: scaling must be exact or refuse, never silently round


def _row(token: str) -> TableRow:
    ref = make_source_ref(page=1, row_idx=0, row_label="Revenue")
    return TableRow(ref=ref, label="Revenue", cells=("Revenue", token))


@pytest.mark.parametrize("digits", [20, 28, 29, 40, 120])
def test_scale_multiplication_is_exact_at_any_width(digits):
    token = "9" * digits
    cell = normalized_cell(
        _row(token), 1, scale=Scale.CRORE, scale_source=ScaleSource.TABLE, currency="INR"
    )
    assert isinstance(cell, NormalizedCell)
    assert cell.value == Decimal(int(token) * 10_000_000)


def _fv(concept, period, value, row=0, scale=Scale.CRORE):
    ref = make_source_ref(page=1, row_idx=row, row_label=concept.value)
    cell = NormalizedCell(ref, value, Decimal(value), scale, ScaleSource.TABLE, "INR")
    return FinancialValue.from_cell(
        concept=concept,
        period=period,
        cell=cell,
        extraction_confidence=ExtractionConfidence.EXACT_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )


def test_derived_sums_are_exact_past_28_digits():
    st, lt = "9" * 30, "1"
    report = MappingReport(
        (_fv(C.SHORT_TERM_BORROWINGS, P24, st, 0), _fv(C.LONG_TERM_BORROWINGS, P24, lt, 1)),
        {},
        (),
        (),
    )
    assert derive_total_debt(report, P24).value == Decimal(int(st) + 1)


# --- 2: sign cancellation must not produce a healthy-looking ratio


def _metrics(*values):
    mapped = {v.concept for v in values}
    report = MappingReport(values, {}, tuple(c for c in C if c not in mapped), ())
    return calculate_metrics(report, (P24, P23))


def test_roe_with_negative_average_equity_is_ambiguous_not_positive():
    ms = _metrics(
        _fv(C.NET_INCOME, P24, "-12455", 0),
        _fv(C.EQUITY, P24, "-8200", 1),
        _fv(C.EQUITY, P23, "-3100", 1),
    )
    roe = ms.metric("roe", P24)
    assert is_unavailable(roe) and roe.reason is UnavailableReason.AMBIGUOUS
    assert "negative" in roe.detail


def test_roa_with_negative_average_assets_is_ambiguous():
    ms = _metrics(
        _fv(C.NET_INCOME, P24, "-5", 0),
        _fv(C.TOTAL_ASSETS, P24, "-10", 1),
        _fv(C.TOTAL_ASSETS, P23, "-10", 1),
    )
    assert ms.metric("roa", P24).reason is UnavailableReason.AMBIGUOUS


def test_ocf_to_net_income_with_a_loss_is_ambiguous():
    ms = _metrics(_fv(C.OPERATING_CASH_FLOW, P24, "-100", 0), _fv(C.NET_INCOME, P24, "-50", 1))
    r = ms.metric("ocf_to_net_income", P24)
    assert is_unavailable(r) and r.reason is UnavailableReason.AMBIGUOUS
    # Negative OCF against a profit stays computable: it reads as bad, honestly.
    ms = _metrics(_fv(C.OPERATING_CASH_FLOW, P24, "-100", 0), _fv(C.NET_INCOME, P24, "50", 1))
    assert ms.metric("ocf_to_net_income", P24).value == Decimal("-2")


def test_hostile_roe_is_no_longer_a_tidy_positive():
    r = pipeline.analyze((FIXTURES / "hostile.pdf").read_bytes())
    assert is_unavailable(r.metric_set.metric("roe", P24))


# --- 7: 21xx years


def test_years_in_the_2100s_parse():
    assert parse_period("FY 2099-00").end_year == 2100
    assert parse_period("2150").end_year == 2150
    assert is_unavailable(parse_period("1899"))
