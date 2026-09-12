"""Period detection. Spec 5.1."""

import pytest

from fincopilot.extract.periods import detect_periods, parse_period
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
