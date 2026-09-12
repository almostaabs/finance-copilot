"""display.py is the only place values are rounded, and it never touches internals."""

from decimal import Decimal

from fincopilot.display import metric_text, money, relative_text, unavailable_text
from fincopilot.types import (
    AnalyticalConfidence,
    Metric,
    MetricUnit,
    Period,
    Scale,
    Unavailable,
    UnavailableReason,
)


def test_money_returns_to_report_scale():
    assert money(Decimal("124500000000"), "INR", Scale.CRORE) == "\u20b912,450.00 crore"
    assert money(Decimal("1500000"), "USD", Scale.MILLION) == "$1.50 million"
    assert money(Decimal("42"), "USD", Scale.UNIT) == "$42.00"
    assert money(Decimal("-1000"), "EUR", Scale.UNIT) == "EUR -1,000.00"


def test_metric_text_by_unit():
    p = Period(2024, "2024")
    pct = Metric(
        "net_margin", p, Decimal("0.12345"), MetricUnit.PERCENT, (), AnalyticalConfidence.HIGH
    )
    ratio = Metric(
        "current_ratio", p, Decimal("1.2349"), MetricUnit.RATIO, (), AnalyticalConfidence.HIGH
    )
    assert metric_text(pct) == "12.3%"
    assert metric_text(ratio) == "1.23x"


def test_relative_text_signs_and_unavailable():
    assert relative_text(Decimal("0.051")) == "+5.1%"
    assert relative_text(Decimal("-0.02")) == "-2.0%"
    assert relative_text(Unavailable(UnavailableReason.DIVISION_BY_ZERO, "zero prior")) == "n/a"


def test_unavailable_text_reports_root_cause():
    root = Unavailable(UnavailableReason.NOT_LOCATED, "no cash flow statement")
    outer = Unavailable(UnavailableReason.MISSING_INPUT, "fcf needs ocf", cause=root)
    assert unavailable_text(outer) == "N/A - not located: no cash flow statement"
