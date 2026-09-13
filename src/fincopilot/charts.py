"""Visual results: Vega-Lite specs built from an AnalysisResult.

Pure. No Streamlit, no I/O. Every number comes from the analysis, converted
once into the report's own scale so an axis reads "8,420" for a report that
prints millions.

The invariant that matters most here: a value that is unavailable is ABSENT
from the data, never plotted as zero. A zero bar is a financial claim. What
could not be drawn is named in `Chart.missing` so the UI can say so in words.

This module owns the single float conversion in the codebase: Vega-Lite specs
are JSON, and JSON has no Decimal. Rounding for display happens here and in
display.py, nowhere else.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any

from fincopilot.display import check_label
from fincopilot.types import (
    SCALE_MULTIPLIER,
    AnalysisResult,
    Metric,
    Period,
    ReconciliationStatus,
    Scale,
    Unavailable,
)
from fincopilot.types import (
    CanonicalConcept as C,
)

# --- dark data-terminal palette ------------------------------------------------
# One family of blues carries the money series, green marks what the business
# wants more of, red what it wants less of, amber the caution. Chosen for
# contrast on a near-black surface: every ink colour clears 4.5:1 on BG.
BG = "#0b0e14"
SURFACE = "#151b26"
INK = "#e6ebf2"
MUTED = "#8b96a8"
GRID = "#212a38"
PRIMARY = "#4da3ff"
# A hue ramp, not a lightness ramp. Darkening a blue to separate series drops
# it under the 3:1 contrast floor on a near-black ground; shifting hue keeps
# every series bright enough to read.
CYAN = "#5ec8e0"
VIOLET = "#9b8cff"
POSITIVE = "#3ddc97"
NEGATIVE = "#ff6b6b"
WARNING = "#ffb454"
FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
DIM_OPACITY = 0.22  # a series switched off in the legend, still faintly present

_SCALE_WORD = {
    Scale.UNIT: "",
    Scale.THOUSAND: "thousand",
    Scale.LAKH: "lakh",
    Scale.MILLION: "million",
    Scale.CRORE: "crore",
    Scale.BILLION: "billion",
}
CENTS = Decimal("0.01")


@dataclass(frozen=True, slots=True)
class Chart:
    """One visual. `rows` is the same data the chart draws, for the detail table."""

    key: str
    title: str
    subtitle: str
    spec: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    missing: tuple[str, ...] = field(default=())


def _f(value: Decimal) -> float:
    """The JSON boundary. Vega-Lite is JSON and JSON has no Decimal."""
    return float(value)


def _q(value: Decimal) -> Decimal:
    return value.quantize(CENTS, rounding=ROUND_HALF_EVEN)


def _periods(result: AnalysisResult) -> tuple[Period, ...]:
    if isinstance(result.periods, Unavailable):
        return ()
    return tuple(sorted(result.periods.ordered, key=lambda p: p.end_year))


def report_scale(result: AnalysisResult) -> Scale:
    """The scale most of the report's own cells were printed in."""
    scales = Counter(v.cell.scale for v in result.values if v.cell is not None)
    return scales.most_common(1)[0][0] if scales else Scale.UNIT


def unit_label(result: AnalysisResult) -> str:
    currency = next((v.currency for v in result.values), "")
    word = _SCALE_WORD[report_scale(result)]
    return f"{currency} {word}".strip()


def _amount(result: AnalysisResult, concept: C, period: Period) -> Decimal | None:
    """The value in the report's own scale, or None when it is unavailable."""
    v = result.metric_set.value(concept, period)
    if isinstance(v, Unavailable):
        return None
    return _q(v.value / SCALE_MULTIPLIER[report_scale(result)])


def _metric(result: AnalysisResult, name: str, period: Period) -> Metric | None:
    m = result.metric_set.metric(name, period)
    return None if isinstance(m, Unavailable) else m


def _base(height: int = 260) -> dict[str, Any]:
    """House style, applied to every chart so they read as one family."""
    return {
        "$schema": "https://vega.github.io/schema/vega-lite/v6.json",
        "height": height,
        "autosize": {"type": "fit", "contains": "padding"},
        "background": "transparent",
        "config": {
            "font": FONT,
            "view": {"stroke": None, "cursor": "pointer"},
            "axis": {
                "labelColor": MUTED,
                "titleColor": MUTED,
                "labelFontSize": 11,
                "labelFontWeight": 500,
                "grid": True,
                "gridColor": GRID,
                "gridDash": [2, 4],
                "domain": False,
                "ticks": False,
                "labelPadding": 8,
            },
            # No axis titles anywhere: a rotated title is hard to read, and a
            # horizontal one collides with the legend. Each chart's subtitle
            # states the unit in words instead.
            "axisY": {"title": None},
            "axisX": {"grid": False, "title": None},
            "legend": {
                "labelColor": INK,
                "labelFontSize": 11,
                "labelFontWeight": 500,
                "orient": "top",
                "direction": "horizontal",
                "title": None,
                "symbolType": "square",
                "symbolSize": 90,
                "offset": 12,
                "labelLimit": 220,
            },
        },
    }


def _interactive(field: str) -> list[dict[str, Any]]:
    """Click a legend swatch to isolate a series; hover to pick out one mark.

    Both are Vega-Lite selection params, so the interaction ships inside the
    spec and needs no callback into Python. The data cannot change from here:
    a selection only ever hides or highlights marks that are already drawn.
    """
    return [
        {"name": "legend_pick", "select": {"type": "point", "fields": [field]}, "bind": "legend"},
        {
            "name": "hovered",
            "select": {"type": "point", "on": "pointerover", "clear": "pointerout"},
        },
    ]


def _emphasis() -> dict[str, Any]:
    """Dim what the legend switched off, lift what the pointer is over.

    Opacity carries both states on purpose. A stroke would also work, but
    Vega-Lite rejects a null default for it, and one channel is easier to read
    than two competing ones."""
    return {
        "opacity": {
            "condition": [
                {"param": "hovered", "empty": False, "value": 1},
                {"param": "legend_pick", "value": 0.9},
            ],
            "value": DIM_OPACITY,
        }
    }


BAND = {"paddingInner": 0.45, "paddingOuter": 0.28}


def _year_axis() -> dict[str, Any]:
    return {
        "field": "period",
        "type": "ordinal",
        "axis": {"title": None, "labelAngle": 0, "grid": False},
        "scale": BAND,
    }


# --- performance ----------------------------------------------------------

PERFORMANCE_SERIES = (
    (C.REVENUE, "Revenue", PRIMARY),
    (C.GROSS_PROFIT, "Gross profit", CYAN),
    (C.OPERATING_INCOME, "Operating income", VIOLET),
    (C.NET_INCOME, "Net income", POSITIVE),
)


def performance_chart(result: AnalysisResult) -> Chart | None:
    """Revenue down to net income, per year. Grouped bars: few periods, and a
    line between two points would imply a trend the data does not carry."""
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for period in _periods(result):
        for concept, label, _ in PERFORMANCE_SERIES:
            amount = _amount(result, concept, period)
            if amount is None:
                missing.append(f"{label} {period.end_year}")
                continue
            rows.append({"period": period.end_year, "series": label, "amount": amount})
    if not rows:
        return None
    order = [label for _, label, _ in PERFORMANCE_SERIES]
    colours = [colour for _, _, colour in PERFORMANCE_SERIES]
    unit = unit_label(result)
    spec = _base() | {
        "data": {"values": [{**r, "amount": _f(r["amount"])} for r in rows]},
        "params": _interactive("series"),
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": _year_axis(),
            "xOffset": {"field": "series", "sort": order},
            "y": {
                "field": "amount",
                "type": "quantitative",
                "axis": {"format": ",.0f"},
            },
            "color": {
                "field": "series",
                "type": "nominal",
                "scale": {"domain": order, "range": colours},
            },
            **_emphasis(),
            "tooltip": [
                {"field": "series", "title": "Item"},
                {"field": "period", "title": "Year"},
                {"field": "amount", "type": "quantitative", "title": unit, "format": ",.2f"},
            ],
        },
    }
    return Chart(
        key="performance",
        title="Revenue and profit",
        subtitle=f"In {unit_label(result)}, as printed in the report.",
        spec=spec,
        rows=tuple(rows),
        missing=tuple(missing),
    )


# --- margins --------------------------------------------------------------

MARGIN_SERIES = (
    ("gross_margin", "Gross margin", CYAN),
    ("operating_margin", "Operating margin", VIOLET),
    ("net_margin", "Net margin", POSITIVE),
)


def margin_chart(result: AnalysisResult) -> Chart | None:
    """Profitability as a share of revenue. The one chart that compares years
    directly, so it carries a rule line at zero."""
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for period in _periods(result):
        for name, label, _ in MARGIN_SERIES:
            m = _metric(result, name, period)
            if m is None:
                missing.append(f"{label} {period.end_year}")
                continue
            rows.append({"period": period.end_year, "series": label, "amount": _q(m.value * 100)})
    if not rows:
        return None
    order = [label for _, label, _ in MARGIN_SERIES]
    colours = [colour for _, _, colour in MARGIN_SERIES]
    spec = _base(220) | {
        "data": {"values": [{**r, "amount": _f(r["amount"])} for r in rows]},
        "params": _interactive("series"),
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": _year_axis(),
            "xOffset": {"field": "series", "sort": order},
            "y": {
                "field": "amount",
                "type": "quantitative",
                "axis": {"format": ".1f", "labelExpr": "datum.label + '%'"},
            },
            "color": {
                "field": "series",
                "type": "nominal",
                "scale": {"domain": order, "range": colours},
            },
            **_emphasis(),
            "tooltip": [
                {"field": "series", "title": "Margin"},
                {"field": "period", "title": "Year"},
                {"field": "amount", "type": "quantitative", "title": "percent", "format": ".1f"},
            ],
        },
    }
    return Chart(
        key="margins",
        title="Margins",
        subtitle="Profit as a percentage of revenue, per year.",
        spec=spec,
        rows=tuple(rows),
        missing=tuple(missing),
    )


# --- balance sheet --------------------------------------------------------

BALANCE_ASSETS = "Assets"
BALANCE_FUNDING = "Liabilities + equity"


def balance_chart(result: AnalysisResult) -> Chart | None:
    """The accounting identity, drawn. Two stacked bars per year that must
    reach the same height; a visible gap is the reconciliation warning."""
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for period in _periods(result):
        assets = _amount(result, C.TOTAL_ASSETS, period)
        liabilities = _amount(result, C.TOTAL_LIABILITIES, period)
        equity = _amount(result, C.EQUITY, period)
        if assets is None or liabilities is None or equity is None:
            absent = [
                name
                for name, value in (
                    ("Total assets", assets),
                    ("Total liabilities", liabilities),
                    ("Equity", equity),
                )
                if value is None
            ]
            missing.append(f"{period.end_year}: {', '.join(absent)} not available")
            continue
        year = period.end_year
        rows.append(
            {"period": year, "side": BALANCE_ASSETS, "part": "Total assets", "amount": assets}
        )
        rows.append(
            {"period": year, "side": BALANCE_FUNDING, "part": "Liabilities", "amount": liabilities}
        )
        rows.append({"period": year, "side": BALANCE_FUNDING, "part": "Equity", "amount": equity})
    if not rows:
        return None
    order = ["Total assets", "Liabilities", "Equity"]
    unit = unit_label(result)
    spec = _base(280) | {
        "data": {"values": [{**r, "amount": _f(r["amount"])} for r in rows]},
        "params": _interactive("part"),
        "mark": {"type": "bar", "cornerRadiusEnd": 3},
        "encoding": {
            "x": _year_axis(),
            "xOffset": {
                "field": "side",
                "sort": [BALANCE_ASSETS, BALANCE_FUNDING],
                "scale": {"paddingInner": 0.16},
            },
            "y": {
                "field": "amount",
                "type": "quantitative",
                "stack": "zero",
                "axis": {"format": ",.0f"},
            },
            "color": {
                "field": "part",
                "type": "nominal",
                "scale": {"domain": order, "range": [PRIMARY, WARNING, POSITIVE]},
            },
            **_emphasis(),
            "tooltip": [
                {"field": "part", "title": "Part"},
                {"field": "side", "title": "Side"},
                {"field": "period", "title": "Year"},
                {"field": "amount", "type": "quantitative", "title": unit, "format": ",.2f"},
            ],
        },
    }
    return Chart(
        key="balance",
        title="What the company owns against how it is funded",
        subtitle=(
            f"In {unit_label(result)}. The two bars for a year should reach the same height; "
            "assets must equal liabilities plus equity."
        ),
        spec=spec,
        rows=tuple(rows),
        missing=tuple(missing),
    )


# --- cash flow ------------------------------------------------------------


def cash_chart(result: AnalysisResult) -> Chart | None:
    """Operating cash flow, less what was spent on assets, to free cash flow.
    A waterfall, because the three figures are additive by construction."""
    periods = _periods(result)
    if not periods:
        return None
    period = periods[-1]
    ocf = _amount(result, C.OPERATING_CASH_FLOW, period)
    capex = _amount(result, C.CAPEX, period)
    fcf = _amount(result, C.FREE_CASH_FLOW, period)
    if ocf is None or capex is None or fcf is None:
        return None
    spend = -abs(capex)
    rows = (
        {
            "series": "Operating cash flow",
            "start": Decimal(0),
            "end": ocf,
            "amount": ocf,
            "kind": "increase" if ocf >= 0 else "decrease",
        },
        {
            "series": "Capital expenditure",
            "start": ocf,
            "end": ocf + spend,
            "amount": spend,
            "kind": "decrease",
        },
        {
            "series": "Free cash flow",
            "start": Decimal(0),
            "end": fcf,
            "amount": fcf,
            "kind": "total",
        },
    )
    unit = unit_label(result)
    spec = _base(240) | {
        "data": {
            "values": [
                {**r, "start": _f(r["start"]), "end": _f(r["end"]), "amount": _f(r["amount"])}
                for r in rows
            ]
        },
        "params": [
            {
                "name": "hovered",
                "select": {"type": "point", "on": "pointerover", "clear": "pointerout"},
            }
        ],
        "mark": {"type": "bar", "cornerRadius": 3, "size": 58},
        "encoding": {
            "x": {
                "field": "series",
                "type": "nominal",
                "sort": [r["series"] for r in rows],
                "axis": {"title": None, "labelAngle": 0, "grid": False},
                "scale": {"paddingInner": 0.6, "paddingOuter": 0.35},
            },
            "y": {
                "field": "start",
                "type": "quantitative",
                "axis": {"format": ",.0f"},
            },
            "y2": {"field": "end"},
            "color": {
                "field": "kind",
                "type": "nominal",
                "legend": None,
                "scale": {
                    "domain": ["increase", "decrease", "total"],
                    "range": [POSITIVE, NEGATIVE, PRIMARY],
                },
            },
            "opacity": {
                "condition": {"param": "hovered", "empty": False, "value": 1},
                "value": 0.88,
            },
            "tooltip": [
                {"field": "series", "title": "Step"},
                {"field": "amount", "type": "quantitative", "title": unit, "format": ",.2f"},
            ],
        },
    }
    return Chart(
        key="cash",
        title=f"Cash generated in {period.end_year}",
        subtitle=(
            f"In {unit_label(result)}. Free cash flow is operating cash flow less capital "
            "expenditure; it is derived, not read from a row."
        ),
        spec=spec,
        rows=rows,
        missing=(),
    )


# --- reconciliation -------------------------------------------------------


def reconciliation_chart(result: AnalysisResult) -> Chart | None:
    """How far each cross-check missed, against the tolerance it is allowed.
    A bar past its tick is the warning, drawn rather than described."""
    periods = _periods(result)
    if not periods:
        return None
    period = periods[-1]
    scale = SCALE_MULTIPLIER[report_scale(result)]
    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for check in result.reconciliations:
        if check.period != period:
            continue
        label = check_label(check.name)
        if check.status is ReconciliationStatus.UNAVAILABLE or isinstance(check.delta, Unavailable):
            missing.append(f"{label}: {check.detail}")
            continue
        rows.append(
            {
                "check": label,
                "amount": _q(abs(check.delta) / scale),
                "tolerance": _q(check.tolerance / scale),
                "status": check.status.value,
                "is_real_zero": True,
            }
        )
    if not rows:
        return None
    spec = _base(max(130, 62 * len(rows))) | {
        "data": {
            "values": [
                {**r, "amount": _f(r["amount"]), "tolerance": _f(r["tolerance"])} for r in rows
            ]
        },
        "params": [
            {
                "name": "hovered",
                "select": {"type": "point", "on": "pointerover", "clear": "pointerout"},
            }
        ],
        "encoding": {
            "y": {
                "field": "check",
                "type": "nominal",
                "axis": {"title": None, "labelLimit": 300, "labelFontSize": 12, "labelColor": INK},
                "sort": [r["check"] for r in rows],
            }
        },
        "layer": [
            {
                # The allowance, drawn first: the coloured bar is read against it.
                "mark": {"type": "bar", "color": SURFACE, "cornerRadiusEnd": 3, "size": 26},
                "encoding": {
                    "x": {
                        "field": "tolerance",
                        "type": "quantitative",
                        "axis": {"format": ",.2f", "tickCount": 6},
                    }
                },
            },
            {
                "mark": {"type": "bar", "cornerRadiusEnd": 2, "size": 12},
                "encoding": {
                    "x": {"field": "amount", "type": "quantitative"},
                    "color": {
                        "field": "status",
                        "type": "nominal",
                        "legend": None,
                        "scale": {"domain": ["passed", "warning"], "range": [POSITIVE, WARNING]},
                    },
                    "tooltip": [
                        {"field": "check", "title": "Check"},
                        {
                            "field": "amount",
                            "type": "quantitative",
                            "title": "Difference",
                            "format": ",.2f",
                        },
                        {
                            "field": "tolerance",
                            "type": "quantitative",
                            "title": "Allowed",
                            "format": ",.2f",
                        },
                    ],
                },
            },
        ],
    }
    return Chart(
        key="reconciliation",
        title=f"Cross-checks for {period.end_year}",
        subtitle=(
            f"In {unit_label(result)}. The grey bar is the difference each check is allowed. "
            "The coloured bar inside it is the difference actually found; no visible bar "
            "means the statement tied out exactly."
        ),
        spec=spec,
        rows=tuple(rows),
        missing=tuple(missing),
    )


BUILDERS = (performance_chart, margin_chart, balance_chart, cash_chart, reconciliation_chart)


def charts(result: AnalysisResult) -> tuple[Chart, ...]:
    """Every chart that has real data behind it, in reading order."""
    if not _periods(result):
        return ()
    return tuple(c for build in BUILDERS if (c := build(result)) is not None)
