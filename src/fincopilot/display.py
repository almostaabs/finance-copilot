"""Presentation formatting. Pure functions; the ONLY place values are rounded.

Internal values stay full-precision Decimal. Everything here is for eyes:
the dashboard, the narrative evidence, the CLI demo.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

from fincopilot.types import (
    SCALE_MULTIPLIER,
    AnalyticalConfidence,
    ExtractionConfidence,
    FinancialValue,
    Metric,
    MetricUnit,
    Scale,
    Unavailable,
)

_SCALE_WORD = {
    Scale.UNIT: "",
    Scale.THOUSAND: "thousand",
    Scale.LAKH: "lakh",
    Scale.MILLION: "million",
    Scale.CRORE: "crore",
    Scale.BILLION: "billion",
}
_CURRENCY_SYMBOL = {"INR": "\u20b9", "USD": "$"}


def money(value: Decimal, currency: str, scale: Scale, *, ascii_only: bool = False) -> str:
    """Base units back to the report's own scale: 124500000000 INR crore -> Rs 12,450.00 crore.

    ascii_only swaps the currency glyph for its ISO code. Small local models
    re-escape non-ASCII glyphs in their output, and the narrative gate then
    reads the escape's digits as numbers."""
    shown = (value / SCALE_MULTIPLIER[scale]).quantize(Decimal("0.01"), rounding=ROUND_HALF_EVEN)
    word = _SCALE_WORD[scale]
    symbol = currency + " " if ascii_only else _CURRENCY_SYMBOL.get(currency, currency + " ")
    return f"{symbol}{shown:,.2f} {word}".strip()


def value_text(v: FinancialValue, *, ascii_only: bool = False) -> str:
    scale = v.cell.scale if v.cell is not None else Scale.UNIT
    return money(v.value, v.currency, scale, ascii_only=ascii_only)


def metric_text(m: Metric) -> str:
    if m.unit is MetricUnit.PERCENT:
        pct = (m.value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
        return f"{pct}%"
    if m.unit is MetricUnit.RATIO:
        return f"{m.value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN)}x"
    return f"{m.value.quantize(Decimal('0.01'), rounding=ROUND_HALF_EVEN):,}"


def relative_text(value: Decimal | Unavailable) -> str:
    if isinstance(value, Unavailable):
        return "n/a"
    pct = (value * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_EVEN)
    return f"{'+' if pct > 0 else ''}{pct}%"


def unavailable_text(u: Unavailable) -> str:
    """Root cause first: the only part a reader can act on."""
    root = u.root()
    return f"N/A - {root.reason.value.replace('_', ' ')}: {root.detail}"


def confidence_text(v: FinancialValue) -> str:
    x = {
        ExtractionConfidence.EXACT_MATCH: "exact label",
        ExtractionConfidence.SYNONYM_MATCH: "known synonym",
        ExtractionConfidence.LLM_MAPPED: "AI-picked row",
        ExtractionConfidence.UNMAPPED: "unmapped",
    }[v.extraction_confidence]
    a = {
        AnalyticalConfidence.HIGH: "high",
        AnalyticalConfidence.MEDIUM: "medium",
        AnalyticalConfidence.LOW: "low",
    }[v.analytical_confidence]
    return f"{x} / {a} confidence"
