"""Number grammars, dash/blank rule, scale and currency detection. Spec 5.2-5.5."""

from decimal import Decimal

import pytest

from fincopilot.extract.units import (
    CellKind,
    classify_cell,
    detect_currency,
    detect_scale,
    parse_number,
    resolve_scale,
)
from fincopilot.types import Scale, ScaleSource, UnavailableReason, is_unavailable

# --- grammars


@pytest.mark.parametrize(
    "token, expected",
    [
        ("12,450.00", "12450.00"),
        ("1,234", "1234"),
        ("123", "123"),
        ("0.50", "0.50"),
        ("12,34,567", "1234567"),  # Indian: 2-digit lead, 2-digit groups, 3-digit tail
        ("1,23,456", "123456"),
        ("12,345", "12345"),  # Western: 2-digit lead then a 3-digit group
        ("999,999,999,999,999,999.00", "999999999999999999.00"),
        ("(1,245.50)", "-1245.50"),
        ("1,245.50-", "-1245.50"),
        ("-1,245.50", "-1245.50"),
        ("+320.50", "320.50"),
        ("(0.00)", "0.00"),
        ("Rs. 1,240.00", "1240.00"),
        ("$1,180.0", "1180.0"),
        ("\u20b9 12,450", "12450"),
        ("1,240.00*", "1240.00"),  # footnote marker glued to the number
        ("1,240.00\u2020", "1240.00"),
    ],
)
def test_parse_number_accepts_both_grammars(token, expected):
    assert parse_number(token) == Decimal(expected)


@pytest.mark.parametrize("token", ["1,2345", "abc", "12,3456", "1,23,45", ",123", "1..2", ""])
def test_parse_number_rejects_what_neither_grammar_accepts(token):
    result = parse_number(token)
    assert is_unavailable(result)
    assert result.reason is UnavailableReason.UNPARSEABLE


def test_parse_number_never_produces_float_or_inf():
    big = parse_number("999,999,999,999,999,999.00")
    assert isinstance(big, Decimal)
    assert big.is_finite()
    assert big == Decimal("999999999999999999.00")


# --- dash vs blank


def test_dash_in_numeric_column_is_zero_and_marked():
    kind, value = classify_cell("\u2014", column_is_numeric=True)
    assert kind is CellKind.DASH_ZERO
    assert value == Decimal(0)


@pytest.mark.parametrize("token", ["-", "\u2013", "\u2014", "Nil", "NIL", "nil"])
def test_every_accepted_dash_token(token):
    kind, _ = classify_cell(token, column_is_numeric=True)
    assert kind is CellKind.DASH_ZERO


def test_blank_is_missing_not_zero():
    kind, value = classify_cell("   ", column_is_numeric=True)
    assert kind is CellKind.MISSING
    assert value is None


def test_dash_plus_other_content_is_unparseable():
    kind, _ = classify_cell("\u2014 see note 14", column_is_numeric=True)
    assert kind is CellKind.UNPARSEABLE


def test_dash_in_non_numeric_column_is_text():
    kind, _ = classify_cell("\u2014", column_is_numeric=False)
    assert kind is CellKind.TEXT


def test_number_cell_is_a_number():
    kind, value = classify_cell("(1,245.50)", column_is_numeric=True)
    assert kind is CellKind.NUMBER
    assert value == Decimal("-1245.50")


# --- scale


@pytest.mark.parametrize(
    "text, scale",
    [
        ("(\u20b9 in crore)", Scale.CRORE),
        ("(Rs. in crore)", Scale.CRORE),
        ("(Rs. in lakhs)", Scale.LAKH),
        ("(Rs. in lacs)", Scale.LAKH),
        ("(\u20b9 in million)", Scale.MILLION),
        ("(In millions, except per share data)", Scale.MILLION),
        ("(in thousands)", Scale.THOUSAND),
        ("(\u20b9 in \u2019000)", Scale.THOUSAND),
        ("(in billions)", Scale.BILLION),
    ],
)
def test_detect_scale_recognises_the_spec_phrases(text, scale):
    assert detect_scale(text) is scale


def test_detect_scale_returns_none_when_absent():
    assert detect_scale("Particulars FY 2023-24 FY 2022-23") is None


def test_resolve_scale_prefers_cell_then_table_then_statement_then_document():
    assert resolve_scale("12 crore", "(in lakhs)", "in millions", "in thousands") == (
        Scale.CRORE,
        ScaleSource.CELL,
    )
    assert resolve_scale("12", "(in lakhs)", "in millions", "in thousands") == (
        Scale.LAKH,
        ScaleSource.TABLE,
    )
    assert resolve_scale("12", "", "in millions", "in thousands") == (
        Scale.MILLION,
        ScaleSource.STATEMENT,
    )
    assert resolve_scale("12", "", "", "in thousands") == (Scale.THOUSAND, ScaleSource.DOCUMENT)
    assert resolve_scale("12", "", "", "") is None


# --- currency


@pytest.mark.parametrize(
    "text, currency",
    [
        ("(Rs. in crore)", "INR"),
        ("(\u20b9 in crore)", "INR"),
        ("INR", "INR"),
        ("(In millions of U.S. dollars)", "USD"),
        ("$", "USD"),
        ("US$ millions", "USD"),
        ("In millions", None),
    ],
)
def test_detect_currency(text, currency):
    assert detect_currency(text) == currency
