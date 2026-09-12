from decimal import Decimal

import pytest

from fincopilot.types import (
    AnalyticalConfidence,
    CanonicalConcept,
    ExtractionConfidence,
    FinancialValue,
    NormalizedCell,
    Period,
    Scale,
    ScaleSource,
)
from tests.helpers import make_source_ref

FY2024 = Period(2024, "FY2024")


def _cell(
    value: str,
    *,
    page: int = 41,
    row_idx: int = 2,
    label: str = "Revenue from operations",
) -> NormalizedCell:
    return NormalizedCell(
        ref=make_source_ref(page=page, row_idx=row_idx, row_label=label),
        raw_token=value,
        value=Decimal(value),
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
    )


def test_mapped_value_carries_its_cell_and_exposes_provenance():
    cell = _cell("124500000000")
    fv = FinancialValue.from_cell(
        concept=CanonicalConcept.REVENUE,
        period=FY2024,
        cell=cell,
        extraction_confidence=ExtractionConfidence.SYNONYM_MATCH,
        analytical_confidence=AnalyticalConfidence.HIGH,
    )
    assert fv.value == Decimal("124500000000")
    assert fv.currency == "INR"
    assert fv.source_refs == ("page_41_table_0_row_2",)
    assert fv.source_page == 41
    assert fv.source_label == "Revenue from operations"
    assert fv.derived_from is None


def test_derived_value_has_no_cell_but_names_its_inputs():
    ebitda = FinancialValue.derived(
        concept=CanonicalConcept.EBITDA,
        period=FY2024,
        # operating_income 19,405,000,000 + d_and_a 6,400,000,000
        value=Decimal("25805000000"),
        currency="INR",
        derived_from=("operating_income", "d_and_a"),
        analytical_confidence=AnalyticalConfidence.HIGH,
    )
    assert ebitda.cell is None
    assert ebitda.derived_from == ("operating_income", "d_and_a")
    assert ebitda.source_refs == ("operating_income", "d_and_a")
    assert ebitda.source_page is None
    assert ebitda.extraction_confidence is ExtractionConfidence.EXACT_MATCH


def test_a_value_must_be_either_mapped_or_derived_never_neither():
    with pytest.raises(ValueError, match="exactly one of cell or derived_from"):
        FinancialValue(
            concept=CanonicalConcept.REVENUE,
            period=FY2024,
            value=Decimal("1"),
            currency="INR",
            extraction_confidence=ExtractionConfidence.UNMAPPED,
            analytical_confidence=AnalyticalConfidence.LOW,
            cell=None,
            derived_from=None,
        )


def test_a_value_must_never_be_both_mapped_and_derived():
    with pytest.raises(ValueError, match="exactly one of cell or derived_from"):
        FinancialValue(
            concept=CanonicalConcept.REVENUE,
            period=FY2024,
            value=Decimal("1"),
            currency="INR",
            extraction_confidence=ExtractionConfidence.EXACT_MATCH,
            analytical_confidence=AnalyticalConfidence.HIGH,
            cell=_cell("1"),
            derived_from=("revenue",),
        )


def test_mapped_value_must_equal_its_cell_value():
    # Guards the core invariant: the number comes from the document, and
    # nothing may quietly substitute a different one.
    with pytest.raises(ValueError, match="must equal its cell value"):
        FinancialValue(
            concept=CanonicalConcept.REVENUE,
            period=FY2024,
            value=Decimal("999"),
            currency="INR",
            extraction_confidence=ExtractionConfidence.EXACT_MATCH,
            analytical_confidence=AnalyticalConfidence.HIGH,
            cell=_cell("124500000000"),
            derived_from=None,
        )


def test_llm_mapped_caps_analytical_confidence_at_medium():
    fv = FinancialValue.from_cell(
        concept=CanonicalConcept.CAPEX,
        period=FY2024,
        cell=_cell(
            "12400000000",
            page=43,
            row_idx=1,
            label="Purchase of property, plant and equipment",
        ),
        extraction_confidence=ExtractionConfidence.LLM_MAPPED,
        analytical_confidence=AnalyticalConfidence.HIGH,  # asked for high
    )
    assert fv.analytical_confidence is AnalyticalConfidence.MEDIUM  # capped


def test_llm_mapped_does_not_raise_a_low_confidence_to_medium():
    fv = FinancialValue.from_cell(
        concept=CanonicalConcept.CAPEX,
        period=FY2024,
        cell=_cell("12400000000", page=43, row_idx=1, label="Capex"),
        extraction_confidence=ExtractionConfidence.LLM_MAPPED,
        analytical_confidence=AnalyticalConfidence.LOW,
    )
    assert fv.analytical_confidence is AnalyticalConfidence.LOW  # cap, not a floor
