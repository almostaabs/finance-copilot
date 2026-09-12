import pytest

from fincopilot.types import (
    CanonicalConcept,
    ExtractedTable,
    Period,
    PeriodMap,
    RawDocument,
    Statement,
    StatementBasis,
    StatementKind,
    StatementSet,
    TableRow,
    Unavailable,
    UnavailableReason,
    is_unavailable,
    make_ref_id,
)
from tests.helpers import make_source_ref


def _row(page: int, row_idx: int, label: str, *cells: str) -> TableRow:
    return TableRow(
        ref=make_source_ref(page=page, table_idx=0, row_idx=row_idx, row_label=label),
        label=label,
        cells=cells,
    )


def test_extracted_table_records_every_page_it_spans():
    # A balance sheet stitched across pages 42 and 43.
    table = ExtractedTable(
        table_id="page_42_table_0",
        first_page=42,
        pages=(42, 43),
        header=("Particulars", "FY2024", "FY2023"),
        rows=(
            _row(42, 0, "Total assets", "13,620.00", "12,160.00"),
            _row(43, 1, "Total equity", "6,930.00", "5,980.00"),
        ),
        caption="(Rs. in crore)",
    )
    assert table.pages == (42, 43)
    # Stitched rows keep their true pages.
    assert table.rows[0].ref.page == 42
    assert table.rows[1].ref.page == 43
    assert table.rows[1].ref.ref_id == make_ref_id(43, 0, 1)


def test_raw_document_indexes_every_row_by_ref_id():
    row = _row(41, 2, "Revenue from operations", "12,450.00", "10,980.00")
    table = ExtractedTable(
        table_id="page_41_table_0",
        first_page=41,
        pages=(41,),
        header=("Particulars", "FY2024", "FY2023"),
        rows=(row,),
        caption=None,
    )
    doc = RawDocument(
        document_id="doc-abc",
        page_count=60,
        page_text=("",) * 60,
        tables=(table,),
        refs={row.ref.ref_id: row.ref},
    )
    assert doc.refs["page_41_table_0_row_2"].row_label == "Revenue from operations"
    assert "page_99_table_0_row_0" not in doc.refs


def test_statement_set_carries_basis_and_may_hold_unavailable_statements():
    table = ExtractedTable("page_41_table_0", 41, (41,), ("Particulars", "FY2024"), (), None)
    income = Statement(
        kind=StatementKind.INCOME,
        basis=StatementBasis.CONSOLIDATED,
        table=table,
    )
    not_found = Unavailable(
        UnavailableReason.NOT_LOCATED,
        "no cash flow statement scored above the minimum",
    )
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=income,
        balance=not_found,
        cash_flow=not_found,
    )
    assert statements.basis is StatementBasis.CONSOLIDATED
    assert not is_unavailable(statements.income)
    assert is_unavailable(statements.balance)
    # One missing statement must not sink the others.
    assert statements.income.kind is StatementKind.INCOME


def test_statement_basis_is_a_closed_three_value_set():
    assert {b.value for b in StatementBasis} == {
        "consolidated",
        "standalone_fallback",
        "unknown",
    }


def test_document_types_are_frozen():
    table = ExtractedTable("page_1_table_0", 1, (1,), ("a",), (), None)
    with pytest.raises(AttributeError):
        table.first_page = 2


def test_period_normalises_indian_fiscal_years_to_the_ending_year():
    fy = Period(end_year=2024, label="FY 2023-24")
    assert fy.end_year == 2024
    assert fy.label == "FY 2023-24"  # original text preserved


def test_periods_sort_by_year_not_by_label():
    older = Period(2023, "Year ended 31 March 2023")
    newer = Period(2024, "FY 2023-24")
    assert sorted([newer, older]) == [older, newer]


def test_periods_with_the_same_year_are_equal_regardless_of_label():
    # Two columns resolving to the same period is a document-level AMBIGUOUS
    # failure, detectable in Phase 3 precisely because these compare equal.
    assert Period(2024, "FY2024") == Period(2024, "March 31, 2024")


def test_period_map_is_keyed_per_statement():
    # golden_us.pdf: three periods on the income statement, two on the balance
    # sheet. A document-level map cannot express this.
    p24, p23, p22 = Period(2024, "2024"), Period(2023, "2023"), Period(2022, "2022")
    pm = PeriodMap(
        columns={
            (StatementKind.INCOME, 1): p24,
            (StatementKind.INCOME, 2): p23,
            (StatementKind.INCOME, 3): p22,
            (StatementKind.BALANCE, 1): p24,
            (StatementKind.BALANCE, 2): p23,
        },
        ordered=(p24, p23, p22),
    )
    assert pm.columns[(StatementKind.INCOME, 3)] == p22
    assert (StatementKind.BALANCE, 3) not in pm.columns
    assert pm.ordered[0] == p24  # newest first
    assert pm.periods_for(StatementKind.BALANCE) == (p24, p23)
    assert pm.periods_for(StatementKind.INCOME) == (p24, p23, p22)
    assert pm.periods_for(StatementKind.CASH_FLOW) == ()


def test_canonical_vocabulary_is_the_closed_set_from_the_spec():
    assert {c.value for c in CanonicalConcept} == {
        "revenue",
        "gross_profit",
        "cogs",
        "operating_income",
        "d_and_a",
        "ebitda",
        "net_income",
        "total_assets",
        "current_assets",
        "cash",
        "total_liabilities",
        "current_liabilities",
        "short_term_borrowings",
        "long_term_borrowings",
        "total_debt",
        "equity",
        "operating_cash_flow",
        "capex",
        "free_cash_flow",
    }
