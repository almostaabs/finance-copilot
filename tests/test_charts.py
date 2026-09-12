"""Visual results. Charts are built from the analysis, never from guesses.

The rule that matters: a period or concept that is unavailable is ABSENT from
the chart data and named in `missing`. It is never plotted as zero, because a
zero bar reads as a real financial fact.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pipeline
import pytest

from fincopilot import charts
from fincopilot.types import SCALE_MULTIPLIER, is_unavailable

GOLDEN_US = Path("tests/fixtures/golden_us.pdf")
GOLDEN_INDIAN = Path("tests/fixtures/golden_indian.pdf")
HOSTILE = Path("tests/fixtures/hostile.pdf")
AMBIGUOUS = Path("tests/fixtures/ambiguous_periods.pdf")


@pytest.fixture(scope="module")
def golden():
    return pipeline.analyze(GOLDEN_US.read_bytes())


@pytest.fixture(scope="module")
def hostile():
    return pipeline.analyze(HOSTILE.read_bytes())


def _rows(chart, **where):
    return [r for r in chart.rows if all(r[k] == v for k, v in where.items())]


# --- units ----------------------------------------------------------------


def test_unit_follows_the_report(golden):
    assert charts.unit_label(golden) == "USD million"
    indian = pipeline.analyze(GOLDEN_INDIAN.read_bytes())
    assert charts.unit_label(indian) == "INR crore"


# --- performance ----------------------------------------------------------


def test_charts_name_their_unit_in_words_not_on_a_rotated_axis(golden):
    """Axis titles collide with the legend; the subtitle carries the unit."""
    for c in charts.charts(golden):
        assert c.spec.get("config", {}).get("axisY", {}).get("title") is None
    money = {"performance", "balance", "cash", "reconciliation"}
    for c in charts.charts(golden):
        if c.key in money:
            assert charts.unit_label(golden) in c.subtitle


def test_performance_chart_values_are_in_report_units(golden):
    c = charts.performance_chart(golden)
    row = _rows(c, period=2024, series="Revenue")[0]
    assert row["amount"] == Decimal("8420.00")
    assert {r["period"] for r in c.rows} == {2022, 2023, 2024}


def test_performance_chart_omits_what_is_missing(hostile):
    c = charts.performance_chart(hostile)
    assert c is not None
    plotted = {(r["series"], r["period"]) for r in c.rows}
    assert ("Operating income", 2024) not in plotted
    assert c.missing


def test_every_plotted_amount_traces_back_to_the_analysis(hostile, golden):
    """The guarantee behind the pictures: a bar exists only where a value does."""
    for result in (hostile, golden):
        c = charts.performance_chart(result)
        if c is None:
            continue
        available = {
            (label, p.end_year)
            for concept, label, _ in charts.PERFORMANCE_SERIES
            for p in result.periods.ordered
            if not is_unavailable(result.metric_set.value(concept, p))
        }
        assert {(r["series"], r["period"]) for r in c.rows} == available
        for r in c.rows:
            concept = next(c for c, label, _ in charts.PERFORMANCE_SERIES if label == r["series"])
            period = next(p for p in result.periods.ordered if p.end_year == r["period"])
            exact = result.metric_set.value(concept, period).value
            assert r["amount"] == charts._q(exact / SCALE_MULTIPLIER[charts.report_scale(result)])


# --- margins --------------------------------------------------------------


def test_margin_chart_is_percent(golden):
    c = charts.margin_chart(golden)
    row = _rows(c, period=2024, series="Net margin")[0]
    assert Decimal("7.5") < row["amount"] < Decimal("7.7")
    assert "%" in c.spec["encoding"]["y"]["axis"]["labelExpr"]
    assert "percentage" in c.subtitle


# --- balance sheet --------------------------------------------------------


def test_balance_chart_puts_the_two_sides_together(golden):
    c = charts.balance_chart(golden)
    periods = {r["period"] for r in c.rows}
    assert periods
    for p in periods:
        assets = sum(r["amount"] for r in _rows(c, period=p, side="Assets"))
        other = sum(r["amount"] for r in _rows(c, period=p, side="Liabilities + equity"))
        assert assets == other


def test_balance_chart_skips_a_period_missing_a_side(hostile):
    c = charts.balance_chart(hostile)
    if c is not None:
        for p in {r["period"] for r in c.rows}:
            assert _rows(c, period=p, side="Assets")


# --- cash flow ------------------------------------------------------------


def test_cash_waterfall_steps_are_additive(golden):
    c = charts.cash_chart(golden)
    steps = {r["series"]: r for r in c.rows}
    assert set(steps) == {"Operating cash flow", "Capital expenditure", "Free cash flow"}
    assert steps["Operating cash flow"]["start"] == Decimal(0)
    assert steps["Capital expenditure"]["start"] == steps["Operating cash flow"]["end"]
    assert steps["Capital expenditure"]["end"] == steps["Free cash flow"]["end"]


def test_cash_chart_absent_when_inputs_are(hostile):
    assert charts.cash_chart(hostile) is None


# --- reconciliation -------------------------------------------------------


def test_reconciliation_chart_compares_delta_with_tolerance(golden):
    c = charts.reconciliation_chart(golden)
    assert c.rows
    for r in c.rows:
        assert r["amount"] >= 0 and r["tolerance"] >= 0
        assert r["status"] in {"passed", "warning"}
    # The allowance is drawn behind the difference, so a perfect tie reads as
    # an empty allowance rather than as an absent chart.
    allowance, difference = c.spec["layer"]
    assert allowance["encoding"]["x"]["field"] == "tolerance"
    assert difference["encoding"]["x"]["field"] == "amount"


def test_reconciliation_checks_are_named_in_words(golden):
    c = charts.reconciliation_chart(golden)
    names = {r["check"] for r in c.rows}
    assert "Assets = liabilities + equity" in names
    assert not any("_" in n for n in names)


def test_reconciliation_chart_survives_a_warning(hostile):
    c = charts.reconciliation_chart(hostile)
    if c is not None:
        assert {r["status"] for r in c.rows} <= {"passed", "warning"}


# --- the set --------------------------------------------------------------


def test_charts_are_json_serialisable(golden):
    for c in charts.charts(golden):
        json.dumps(c.spec)  # raises if a Decimal leaked into the spec


def test_ambiguous_periods_produce_no_charts():
    result = pipeline.analyze(AMBIGUOUS.read_bytes())
    assert charts.charts(result) == ()


def test_every_chart_has_a_title_and_a_key(golden):
    seen = set()
    for c in charts.charts(golden):
        assert c.title and c.subtitle and c.key not in seen
        seen.add(c.key)


MONEY_PATH = (
    "types.py",
    "display.py",
    "views.py",
    "extract/units.py",
    "mapping/synonyms.py",
    "mapping/validate.py",
    "calc/ratios.py",
    "calc/trends.py",
    "calc/reconcile.py",
    "rules/redflags.py",
)


@pytest.mark.parametrize("name", MONEY_PATH)
def test_no_float_anywhere_on_the_money_path(name):
    """Decimal end to end. charts.py converts once, at the Vega JSON boundary."""
    assert "float(" not in (Path("src/fincopilot") / name).read_text(encoding="utf-8")


def test_charts_is_the_only_place_money_becomes_a_float():
    source = Path("src/fincopilot/charts.py").read_text(encoding="utf-8")
    assert source.count("float(") == 1  # the single _f helper
