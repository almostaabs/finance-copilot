"""Statements printed without ruling lines. Phase 12 extraction rework.

text_aligned.pdf encodes the four real-report cases met in Phase 12:
whitespace-aligned columns with '$' signs, a Notes column, a continuation
page that repeats heading and header, and a year-less convenience column.
"""

from decimal import Decimal
from pathlib import Path

import pipeline
import pytest

from fincopilot.extract.textgrid import Word, text_grid
from fincopilot.types import CanonicalConcept as C
from fincopilot.types import Period, ReconciliationStatus

PDF = Path("tests/fixtures/text_aligned.pdf")
P24, P23 = Period(2024, "2024"), Period(2023, "2023")


def _w(text: str, x1: float, top: float, width: float = 30) -> Word:
    return Word(text, x1 - width, x1, top)


def _statement(rows: list[tuple[str, tuple[str, ...]]], years=("2024", "2023")) -> list[Word]:
    cols = (400, 470, 540)
    words = [_w(y, x, 50, 20) for y, x in zip(years, cols, strict=False)]
    top = 70
    for label, values in rows:
        words.append(Word(label, 60, 60 + 6 * len(label), top))
        words += [_w(v, x, top) for v, x in zip(values, cols, strict=False) if v]
        top += 13
    return words


# --- unit -----------------------------------------------------------------


def test_grid_from_right_aligned_columns():
    rows, col_x = text_grid(
        _statement(
            [("Revenue", ("1,000", "900")), ("Cost", ("(400)", "(350)")), ("Net", ("600", "550"))]
        )
    )
    assert rows[0] == ["", "2024", "2023"]
    assert rows[1] == ["Revenue", "1,000", "900"]
    assert rows[2] == ["Cost", "(400)", "(350)"]
    assert col_x[0] == 60.0 and len(col_x) == 3


def test_split_closing_paren_is_joined():
    words = _statement([("A", ("(400", "1")), ("B", ("2", "3")), ("C", ("4", "5"))])
    words.append(Word(")", 401, 406, 70))  # a ')' set in its own column
    rows, _ = text_grid(words)
    assert rows[1][1] == "(400)"


def test_notes_column_dropped_and_year_less_column_dropped():
    words = _statement(
        [("Cash", ("29,965", "23,646")), ("Debt", ("1", "2")), ("Equity", ("3", "4"))]
    )
    for i, top in enumerate((70, 83, 96)):
        words.append(_w(str(4 + i), 330, top, 10))  # notes: small ints, no year above
        words.append(_w("999", 610, top))  # convenience column, no year above
    rows, col_x = text_grid(words)
    assert rows[0] == ["", "2024", "2023"]
    assert rows[1] == ["Cash", "29,965", "23,646"]
    assert len(col_x) == 3


def test_too_little_returns_none():
    assert text_grid([]) is None
    assert text_grid(_statement([("Only", ("1", "2"))])) is None
    no_years = _statement([("A", ("1", "2")), ("B", ("3", "4")), ("C", ("5", "6"))], years=())
    assert text_grid(no_years) is None


def test_trailing_comma_is_not_an_amount():
    words = _statement([("A", ("1", "2")), ("B", ("3", "4")), ("C", ("5", "6"))])
    words.append(_w("September 30,", 400, 40))  # sits above the years, must not become a row
    rows, _ = text_grid(words)
    assert rows[0] == ["", "2024", "2023"]


# --- end to end -----------------------------------------------------------


@pytest.fixture(scope="module")
def result():
    return pipeline.analyze(PDF.read_bytes())


def test_periods_and_basis(result):
    assert result.basis.value == "consolidated"
    assert [p.end_year for p in result.periods.ordered] == [2024, 2023, 2022]


def test_income_values_with_dollar_signs(result):
    assert result.metric_set.value(C.REVENUE, P24).value == Decimal("383285000000")
    assert result.metric_set.value(C.NET_INCOME, P24).value == Decimal("96995000000")
    assert result.metric_set.value(C.NET_INCOME, P24).source_page == 1


def test_balance_sheet_stitched_across_repeated_heading(result):
    assert result.metric_set.value(C.TOTAL_ASSETS, P24).source_page == 2
    assert result.metric_set.value(C.TOTAL_LIABILITIES, P24).source_page == 3
    assert result.metric_set.value(C.EQUITY, P23).value == Decimal("50672000000")


def test_notes_column_never_becomes_a_period(result):
    assert all(p.end_year >= 2022 for p in result.periods.ordered)
    assert result.metric_set.value(C.CASH, P24).value == Decimal("29965000000")


def test_cash_flow_ignores_convenience_column(result):
    assert result.metric_set.value(C.OPERATING_CASH_FLOW, P24).value == Decimal("110543000000")
    assert result.metric_set.value(C.CAPEX, P24).value == Decimal("-10959000000")
    assert result.metric_set.value(C.FREE_CASH_FLOW, P24).value == Decimal("99584000000")


def test_every_reconciliation_passes(result):
    checks = [c for c in result.reconciliations if c.period == P24]
    assert checks and all(c.status is ReconciliationStatus.PASSED for c in checks)
