from decimal import Decimal

import pytest

from fincopilot.types import (
    SCALE_MULTIPLIER,
    AnalyticalConfidence,
    ExtractionConfidence,
    NormalizedCell,
    Scale,
    ScaleSource,
    SourceRef,
    make_ref_id,
)


def test_ref_id_format_is_document_local_and_stable():
    assert make_ref_id(page=12, table_idx=1, row_idx=4) == "page_12_table_1_row_4"


def test_source_ref_keeps_the_true_page():
    # A row stitched from page 143 must still report page 143.
    ref = SourceRef(
        ref_id=make_ref_id(143, 1, 7),
        document_id="doc-abc",
        page=143,
        table_idx=1,
        row_idx=7,
        col_idx=2,
        row_label="Total equity",
        raw_text="6,930.00",
    )
    assert ref.ref_id == "page_143_table_1_row_7"
    assert ref.page == 143


def test_source_ref_is_frozen():
    ref = SourceRef("page_1_table_0_row_0", "doc", 1, 0, 0, None, "Revenue", "12,450.00")
    with pytest.raises(AttributeError):
        ref.page = 2


def test_every_scale_has_a_multiplier():
    assert set(SCALE_MULTIPLIER) == set(Scale)
    assert SCALE_MULTIPLIER[Scale.CRORE] == Decimal(10_000_000)
    assert SCALE_MULTIPLIER[Scale.LAKH] == Decimal(100_000)
    assert SCALE_MULTIPLIER[Scale.MILLION] == Decimal(1_000_000)
    assert SCALE_MULTIPLIER[Scale.UNIT] == Decimal(1)


def test_normalized_cell_stores_base_units_and_keeps_display_scale():
    ref = SourceRef(
        "page_41_table_0_row_2", "doc", 41, 0, 2, 1, "Revenue from operations", "12,450.00"
    )
    cell = NormalizedCell(
        ref=ref,
        raw_token="12,450.00",
        value=Decimal("124500000000"),  # 12,450.00 crore in base units
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
    )
    assert cell.value == Decimal("124500000000")
    assert cell.scale is Scale.CRORE
    assert cell.scale_source is ScaleSource.TABLE
    assert cell.raw_token == "12,450.00"
    assert cell.dash_zero is False


def test_dash_zero_is_recorded_so_reconciliation_can_name_it():
    ref = SourceRef("page_42_table_0_row_9", "doc", 42, 0, 9, 1, "Exceptional items", "—")
    cell = NormalizedCell(
        ref=ref,
        raw_token="—",
        value=Decimal(0),
        scale=Scale.CRORE,
        scale_source=ScaleSource.TABLE,
        currency="INR",
        dash_zero=True,
    )
    assert cell.value == Decimal(0)
    assert cell.dash_zero is True
    assert cell.raw_token == "—"


def test_confidence_axes_are_independent_closed_sets():
    assert {c.value for c in ExtractionConfidence} == {
        "exact_match",
        "synonym_match",
        "llm_mapped",
        "unmapped",
    }
    assert {c.value for c in AnalyticalConfidence} == {"high", "medium", "low"}
