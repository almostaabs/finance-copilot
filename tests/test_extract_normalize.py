"""normalize_document: StatementSet + PeriodMap -> NormalizedTables. Spec 5.2-5.5."""

from decimal import Decimal
from pathlib import Path

import pytest

from fincopilot.extract.locate import locate_statements
from fincopilot.extract.pdf import extract_pdf, validate_input
from fincopilot.extract.periods import detect_periods
from fincopilot.extract.units import normalize_document
from fincopilot.types import (
    NormalizedTables,
    Scale,
    ScaleSource,
    UnavailableReason,
    is_unavailable,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _normalize(name: str) -> NormalizedTables:
    data = (FIXTURES / name).read_bytes()
    doc = extract_pdf(data, validate_input(data))
    statements = locate_statements(doc)
    periods = detect_periods(statements)
    return normalize_document(statements, periods, doc)


@pytest.fixture(scope="module")
def indian():
    return _normalize("golden_indian.pdf")


@pytest.fixture(scope="module")
def us():
    return _normalize("golden_us.pdf")


def _cell(table, label: str, col: int):
    row = next(r for r in table.table.rows if r.label == label)
    return table.cells[(row.ref.ref_id, col)]


def test_indian_scale_comes_from_the_table_caption(indian):
    inc = indian.income
    assert inc.scale.scale is Scale.CRORE
    assert inc.scale.source is ScaleSource.TABLE
    assert inc.currency == "INR"


def test_indian_values_are_decimal_in_base_units(indian):
    cell = _cell(indian.income, "Revenue from operations", 1)
    assert isinstance(cell.value, Decimal)
    assert cell.value == Decimal("124500000000")
    assert cell.raw_token == "12,450.00"
    assert cell.ref.page == 41
    assert cell.ref.col_idx == 1
    assert cell.ref.ref_id == "page_41_table_0_row_0"


def test_parenthesised_capex_is_negative_at_the_cell_level(indian):
    cell = _cell(indian.cash_flow, "Purchase of property, plant and equipment", 1)
    assert cell.value == Decimal("-12400000000")


def test_us_currency_is_inferred_from_document_evidence(us):
    # "(In millions)" names no currency; the 10-K cover does.
    assert us.income.currency == "USD"
    assert us.income.scale.scale is Scale.MILLION
    assert _cell(us.income, "Net sales", 1).value == Decimal("8420000000")
    assert _cell(us.balance, "Total assets", 2).value == Decimal("6950000000")


def test_columns_outside_the_period_map_are_not_normalised(us):
    row = next(r for r in us.balance.table.rows if r.label == "Total assets")
    assert (row.ref.ref_id, 3) not in us.balance.cells


def test_no_scale_anywhere_is_ambiguous_for_every_value():
    n = _normalize("no_scale.pdf")
    assert is_unavailable(n.income)
    assert n.income.reason is UnavailableReason.AMBIGUOUS


def test_ambiguous_periods_propagate_as_the_cause():
    n = _normalize("ambiguous_periods.pdf")
    assert is_unavailable(n.income)
    assert n.income.root().reason is UnavailableReason.AMBIGUOUS


def test_missing_statement_passes_through():
    n = _normalize("standalone_only.pdf")
    assert is_unavailable(n.cash_flow)
    assert n.cash_flow.reason is UnavailableReason.NOT_LOCATED
    assert not is_unavailable(n.income)


def test_hostile_cells_are_classified_not_guessed():
    n = _normalize("hostile.pdf")
    inc = n.income
    big = _cell(inc, "Revenue from operations", 1)
    assert big.value == Decimal("9999999999999999990000000")
    assert big.value.is_finite()

    dash = _cell(inc, "Cost of materials consumed", 1)
    assert dash.value == Decimal(0)
    assert dash.dash_zero is True
    assert dash.raw_token == "\u2014"

    blank = _cell(inc, "Cost of materials consumed", 2)
    assert is_unavailable(blank)
    assert blank.reason is UnavailableReason.MISSING_INPUT

    note = _cell(inc, "Exceptional items", 1)
    assert is_unavailable(note)
    assert note.reason is UnavailableReason.UNPARSEABLE

    assert _cell(inc, "Exceptional items", 2).value == Decimal(0)
    assert _cell(inc, "Depreciation and amortisation expense", 1).value == Decimal("1234560000000")
    assert _cell(inc, "Depreciation and amortisation expense", 2).value == Decimal("12345670000000")
    assert is_unavailable(_cell(inc, "Profit from operations", 1))
    assert is_unavailable(_cell(inc, "Profit from operations", 2))
    assert _cell(inc, "Profit for the year", 1).value == Decimal("-12455000000")

    assert _cell(n.balance, "Total equity", 1).value == Decimal("-8200000000")
