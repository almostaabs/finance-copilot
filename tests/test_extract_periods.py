"""Period detection. Spec 5.1."""

import pytest

from fincopilot.extract.periods import detect_periods, parse_period, reconcile_fiscal_years
from fincopilot.types import (
    ExtractedTable,
    Statement,
    StatementBasis,
    StatementKind,
    StatementSet,
    Unavailable,
    UnavailableReason,
    is_unavailable,
)


@pytest.mark.parametrize(
    "label, end_year",
    [
        ("2024", 2024),
        ("FY2024", 2024),
        ("FY 2024", 2024),
        ("FY 2023-24", 2024),
        ("2023-24", 2024),
        ("FY 2023-2024", 2024),
        ("March 31, 2024", 2024),
        ("As at 31 March 2024", 2024),
        ("Year ended 31 March 2024", 2024),
        ("Fiscal 2024", 2024),
        ("December 31, 2022", 2022),
    ],
)
def test_parse_period_normalises_to_the_ending_year(label, end_year):
    p = parse_period(label)
    assert not is_unavailable(p)
    assert p.end_year == end_year
    assert p.label == label  # original text preserved


@pytest.mark.parametrize("label", ["Particulars", "", "Notes", "Amount"])
def test_parse_period_without_a_year_is_unavailable(label):
    assert is_unavailable(parse_period(label))


def _stmt(kind: StatementKind, header: tuple[str, ...]) -> Statement:
    table = ExtractedTable(f"t_{kind.value}", 1, (1,), header, (), None)
    return Statement(kind=kind, basis=StatementBasis.CONSOLIDATED, table=table)


NOT_FOUND = Unavailable(UnavailableReason.NOT_LOCATED, "missing")


def test_detect_periods_is_keyed_per_statement():
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_stmt(StatementKind.INCOME, ("", "2024", "2023", "2022")),
        balance=_stmt(StatementKind.BALANCE, ("", "2024", "2023")),
        cash_flow=_stmt(StatementKind.CASH_FLOW, ("", "2024", "2023", "2022")),
    )
    pm = detect_periods(statements)
    assert not is_unavailable(pm)
    assert [p.end_year for p in pm.ordered] == [2024, 2023, 2022]
    assert [p.end_year for p in pm.periods_for(StatementKind.BALANCE)] == [2024, 2023]
    assert pm.columns[(StatementKind.INCOME, 3)].end_year == 2022
    assert (StatementKind.BALANCE, 3) not in pm.columns


def test_column_order_comes_from_parsed_years_not_position():
    # Oldest year printed first: position must not be trusted.
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_stmt(StatementKind.INCOME, ("Particulars", "FY 2022-23", "FY 2023-24")),
        balance=NOT_FOUND,
        cash_flow=NOT_FOUND,
    )
    pm = detect_periods(statements)
    assert pm.columns[(StatementKind.INCOME, 1)].end_year == 2023
    assert pm.columns[(StatementKind.INCOME, 2)].end_year == 2024
    assert pm.ordered[0].end_year == 2024


def test_two_columns_resolving_to_one_year_is_ambiguous():
    header = ("Particulars", "FY 2023-24", "Year ended 31 March 2024")
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_stmt(StatementKind.INCOME, header),
        balance=NOT_FOUND,
        cash_flow=NOT_FOUND,
    )
    pm = detect_periods(statements)
    assert is_unavailable(pm)
    assert pm.reason is UnavailableReason.AMBIGUOUS


def test_header_without_a_year_is_ambiguous():
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_stmt(StatementKind.INCOME, ("Particulars", "Current", "Previous")),
        balance=NOT_FOUND,
        cash_flow=NOT_FOUND,
    )
    pm = detect_periods(statements)
    assert is_unavailable(pm)
    assert pm.reason is UnavailableReason.AMBIGUOUS


def test_missing_statements_are_skipped_not_fatal():
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_stmt(StatementKind.INCOME, ("Particulars", "FY 2023-24", "FY 2022-23")),
        balance=NOT_FOUND,
        cash_flow=NOT_FOUND,
    )
    pm = detect_periods(statements)
    assert pm.periods_for(StatementKind.BALANCE) == ()
    assert len(pm.ordered) == 2


# --- T1.1-g: "Fiscal YYYY" statements beside a date-headed balance sheet ----

HD_INCOME = "CONSOLIDATED STATEMENTS OF EARNINGS\nFiscal Fiscal Fiscal\nin millions 2025 2024 2023"
HD_BALANCE = "CONSOLIDATED BALANCE SHEETS\nFebruary 1, February 2,\nin millions 2026 2025"
HD_BINDING = (
    "fiscal 2024 Fiscal year ended February 2, 2025 (includes 53 weeks)\n"
    "fiscal 2025 Fiscal year ended February 1, 2026 (includes 52 weeks)"
)


def _paged(kind: StatementKind, header: tuple[str, ...], page: int) -> Statement:
    table = ExtractedTable(f"t_{kind.value}", page, (page,), header, (), None)
    return Statement(kind=kind, basis=StatementBasis.CONSOLIDATED, table=table)


def _reconcile(front: str, balance: str = HD_BALANCE):
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_paged(StatementKind.INCOME, ("", "2025", "2024", "2023"), 2),
        balance=_paged(StatementKind.BALANCE, ("", "2026", "2025"), 3),
        cash_flow=NOT_FOUND,
    )
    return reconcile_fiscal_years(
        statements, detect_periods(statements), (front, HD_INCOME, balance)
    )


def test_a_one_sentence_binding_relabels_the_date_headed_columns():
    out = _reconcile(HD_BINDING)
    assert out.periods_for(StatementKind.BALANCE)[0].end_year == 2025
    assert [p.end_year for p in out.periods_for(StatementKind.BALANCE)] == [2025, 2024]
    label = out.columns[(StatementKind.BALANCE, 1)].label
    assert "p1" in label and "ended February 1, 2026" in label
    assert [p.end_year for p in out.periods_for(StatementKind.INCOME)] == [2025, 2024, 2023]


def test_mixed_headers_without_a_binding_are_ambiguous():
    out = _reconcile("Our fiscal year ends on the Sunday nearest January 31.")
    assert out.reason is UnavailableReason.AMBIGUOUS
    assert "income headed by fiscal year, balance by end date" in out.detail


def test_conflicting_bindings_are_ambiguous_and_quote_both():
    out = _reconcile(HD_BINDING + "\nfiscal 2026 Fiscal year ended February 1, 2026")
    assert out.reason is UnavailableReason.AMBIGUOUS
    assert "fiscal 2025 Fiscal year ended February 1, 2026" in out.detail
    assert "fiscal 2026 Fiscal year ended February 1, 2026" in out.detail


def test_a_binding_date_matching_no_balance_column_is_ambiguous():
    out = _reconcile(HD_BINDING.replace("February 1, 2026", "January 31, 2026"))
    assert out.reason is UnavailableReason.AMBIGUOUS


def test_a_date_only_filing_is_untouched():
    dated = (
        "CONSOLIDATED STATEMENTS OF EARNINGS\nJanuary 30, January 31, February 2,\n2026 2025 2024"
    )
    statements = StatementSet(
        basis=StatementBasis.CONSOLIDATED,
        income=_paged(StatementKind.INCOME, ("", "2026", "2025", "2024"), 2),
        balance=_paged(StatementKind.BALANCE, ("", "2026", "2025"), 3),
        cash_flow=NOT_FOUND,
    )
    periods = detect_periods(statements)
    out = reconcile_fiscal_years(statements, periods, (HD_BINDING, dated, HD_BALANCE))
    assert out is periods
