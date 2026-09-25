"""Deterministic red-flag rules. Spec 7.5.

Each rule is data: an id, a severity, a template, and a predicate over the
analysis. The RULE decides whether it fires. A model may later explain a
rule that fired; it never decides that one did. Unavailable inputs produce
NOT_EVALUATED with the reason, never a silent pass.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal

from fincopilot.types import CanonicalConcept as C
from fincopilot.types import (
    ExtractionConfidence,
    FinancialValue,
    MappingReport,
    Maybe,
    Metric,
    MetricSet,
    Period,
    ReconciliationReport,
    RedFlag,
    RuleOutcome,
    Severity,
    Trend,
    TrendSet,
    Unavailable,
    UnavailableReason,
)

# --- Editorial MVP thresholds. One block, documented, configurable later. ---
# earnings_quality at 0.7 is a conventional but arbitrary screen.
# leverage_increase needs BOTH a delta and an absolute floor, so a 0.1 -> 0.4
# move is deliberately suppressed.
MARGIN_COMPRESSION_BPS = Decimal("0.02")  # 200 bps, margins are ratios
LEVERAGE_INCREASE_DELTA = Decimal("0.25")
LEVERAGE_INCREASE_FLOOR = Decimal("1.0")
HIGH_LEVERAGE = Decimal("2.0")
WEAK_LIQUIDITY = Decimal("1.0")
EARNINGS_QUALITY = Decimal("0.7")
# implausible_magnitude is an INFO screen, never a correction. Real companies'
# asset turnover is well below 20; a 100x change in one year in revenue, assets
# or equity almost always means a scale or parsing error, not business reality.
MAGNITUDE_JUMP_FACTOR = Decimal(100)
ASSET_TURNOVER_CEILING = Decimal(20)


@dataclass(frozen=True, slots=True)
class Inputs:
    metrics: MetricSet
    trends: TrendSet
    reconciliations: ReconciliationReport
    mapping: MappingReport
    period: Period


@dataclass(frozen=True, slots=True)
class Verdict:
    fired: bool
    refs: tuple[str, ...] = ()
    detail: str = ""


@dataclass(frozen=True, slots=True)
class Rule:
    rule_id: str
    severity: Severity
    fired_template: str
    clear_template: str
    predicate: Callable[[Inputs], Maybe[Verdict]]


def _refs(*items) -> tuple[str, ...]:
    out: list[str] = []
    for x in items:
        if isinstance(x, Metric):
            out.extend(x.inputs)
        elif isinstance(x, FinancialValue):
            out.extend(x.source_refs)
    return tuple(dict.fromkeys(out))


def _need(*items) -> Unavailable | None:
    for x in items:
        if isinstance(x, Unavailable):
            return x
    return None


def _revenue_decline(i: Inputs) -> Maybe[Verdict]:
    t = i.trends.get(C.REVENUE.value, i.period)
    if isinstance(t, Unavailable):
        return t
    v = i.metrics.value(C.REVENUE, i.period)
    return Verdict(t.absolute_change < 0, _refs(v), f"revenue change {t.absolute_change}")


def _margin_compression(i: Inputs) -> Maybe[Verdict]:
    found: list[tuple[str, Trend]] = []
    causes: list[Unavailable] = []
    for name in ("gross_margin", "operating_margin"):
        t = i.trends.get(name, i.period)
        if isinstance(t, Unavailable):
            causes.append(t)
        else:
            found.append((name, t))
    if not found:
        return causes[0]
    hits = [(n, t) for n, t in found if t.absolute_change < -MARGIN_COMPRESSION_BPS]
    refs = _refs(*(i.metrics.metric(n, i.period) for n, _ in found))
    detail = ", ".join(f"{n} {_num(t.absolute_change)}" for n, t in found)
    return Verdict(bool(hits), refs, detail)


def _leverage_increase(i: Inputs) -> Maybe[Verdict]:
    t = i.trends.get("debt_to_equity", i.period)
    m = i.metrics.metric("debt_to_equity", i.period)
    if (u := _need(t, m)) is not None:
        return u
    fired = t.absolute_change > LEVERAGE_INCREASE_DELTA and m.value > LEVERAGE_INCREASE_FLOOR
    return Verdict(fired, _refs(m), f"D/E {_num(m.value)}, change {_num(t.absolute_change)}")


def _num(value: Decimal) -> str:
    """A Decimal for a human-readable rule message. Rounding here is presentation
    only; the rule itself compares the full-precision value."""
    if abs(value) >= 1000:
        return f"{value.quantize(Decimal(1), rounding=ROUND_HALF_EVEN):,}"
    shown = value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN).normalize()
    return f"{shown:f}"


def _threshold(name: str, op: Callable[[Decimal], bool]) -> Callable[[Inputs], Maybe[Verdict]]:
    def predicate(i: Inputs) -> Maybe[Verdict]:
        m = i.metrics.metric(name, i.period)
        if isinstance(m, Unavailable):
            return m
        return Verdict(op(m.value), _refs(m), f"{name} {_num(m.value)}")

    return predicate


def _negative_value(concept: C) -> Callable[[Inputs], Maybe[Verdict]]:
    def predicate(i: Inputs) -> Maybe[Verdict]:
        v = i.metrics.value(concept, i.period)
        if isinstance(v, Unavailable):
            return v
        return Verdict(v.value < 0, _refs(v), f"{concept.value} {_num(v.value)}")

    return predicate


def _earnings_quality(i: Inputs) -> Maybe[Verdict]:
    ocf = i.metrics.value(C.OPERATING_CASH_FLOW, i.period)
    ni = i.metrics.value(C.NET_INCOME, i.period)
    ratio = i.metrics.metric("ocf_to_net_income", i.period)
    if (u := _need(ocf, ni, ratio)) is not None:
        return u
    both_positive = ocf.value > 0 and ni.value > 0
    fired = both_positive and ratio.value < EARNINGS_QUALITY
    return Verdict(fired, _refs(ratio), f"OCF/NI {_num(ratio.value)}")


def _reconciliation_warning(i: Inputs) -> Maybe[Verdict]:
    checks = [c for c in i.reconciliations.checks if c.period == i.period]
    live = [c for c in checks if c.status.value != "unavailable"]
    if not live:
        return Unavailable(UnavailableReason.MISSING_INPUT, "no reconciliation could run")
    warn = [c for c in live if c.status.value == "warning"]
    refs = tuple(dict.fromkeys(r for c in warn for r in c.refs))
    return Verdict(bool(warn), refs, "; ".join(c.name for c in warn))


def _low_confidence_kpi(i: Inputs) -> Maybe[Verdict]:
    weak: list[str] = []
    refs: list[str] = []
    for concept in (C.REVENUE, C.NET_INCOME):
        v = i.mapping.get(concept, i.period)
        if isinstance(v, Unavailable):
            weak.append(f"{concept.value} unmapped")
        elif v.extraction_confidence is ExtractionConfidence.LLM_MAPPED:
            weak.append(f"{concept.value} llm_mapped")
            refs.extend(v.source_refs)
    return Verdict(bool(weak), tuple(refs), ", ".join(weak))


def _prior_period(i: Inputs) -> Period | None:
    """The newest period strictly older than the one under evaluation."""
    older = {v.period for v in i.metrics.values if v.period < i.period}
    return max(older) if older else None


def _implausible_magnitude(i: Inputs) -> Maybe[Verdict]:
    """A 100x year-over-year jump, or revenue above 20x total assets. Flags, never alters."""
    hits: list[str] = []
    hit_values: list[FinancialValue] = []
    seen: list[FinancialValue] = []
    causes: list[Unavailable] = []
    year = i.period.end_year
    prior = _prior_period(i)
    for concept in (C.REVENUE, C.TOTAL_ASSETS, C.EQUITY):
        a = i.metrics.value(concept, i.period)
        b = (
            i.metrics.value(concept, prior)
            if prior is not None
            else Unavailable(UnavailableReason.MISSING_INPUT, f"no period before {year}")
        )
        if (u := _need(a, b)) is not None:
            causes.append(u)
            continue
        if a.value == 0 or b.value == 0:
            zero_year = year if a.value == 0 else prior.end_year
            causes.append(
                Unavailable(
                    UnavailableReason.DIVISION_BY_ZERO,
                    f"{concept.value} {zero_year} is zero",
                    refs=_refs(a, b),
                )
            )
            continue
        seen.extend((a, b))
        big, small = max(abs(a.value), abs(b.value)), min(abs(a.value), abs(b.value))
        if big / small >= MAGNITUDE_JUMP_FACTOR:
            hits.append(f"{concept.value} {prior.end_year}->{year} changed {_num(big / small)}x")
            hit_values.extend((a, b))

    revenue = i.metrics.value(C.REVENUE, i.period)
    assets = i.metrics.value(C.TOTAL_ASSETS, i.period)
    if (u := _need(revenue, assets)) is not None:
        causes.append(u)
    elif assets.value <= 0:
        causes.append(
            Unavailable(
                UnavailableReason.DIVISION_BY_ZERO,
                f"total_assets {year} is not positive",
                refs=_refs(assets),
            )
        )
    else:
        seen.extend((revenue, assets))
        turnover = revenue.value / assets.value
        if turnover > ASSET_TURNOVER_CEILING:
            hits.append(f"revenue/total_assets {year} is {_num(turnover)}")
            hit_values.extend((revenue, assets))

    if hits:
        return Verdict(True, _refs(*hit_values), "; ".join(hits))
    if seen:
        return Verdict(False, _refs(*seen))
    return Unavailable(
        UnavailableReason.MISSING_INPUT, "no magnitude check could run", cause=causes[0]
    )


def _rule(rule_id, severity, fired, clear, predicate) -> Rule:
    return Rule(rule_id, severity, fired, clear, predicate)


RULES: tuple[Rule, ...] = (
    _rule(
        "revenue_decline",
        Severity.WARNING,
        "Revenue fell year over year ({detail}).",
        "Revenue did not fall year over year.",
        _revenue_decline,
    ),
    _rule(
        "margin_compression",
        Severity.WARNING,
        "Margin compressed more than 200 bps ({detail}).",
        "No margin compression beyond 200 bps.",
        _margin_compression,
    ),
    _rule(
        "leverage_increase",
        Severity.WARNING,
        "Debt-to-equity rose more than 0.25 and exceeds 1.0 ({detail}).",
        "No material leverage increase.",
        _leverage_increase,
    ),
    _rule(
        "high_leverage",
        Severity.CRITICAL,
        "Debt-to-equity above 2.0 ({detail}).",
        "Debt-to-equity at or below 2.0.",
        _threshold("debt_to_equity", lambda v: v > HIGH_LEVERAGE),
    ),
    _rule(
        "negative_fcf",
        Severity.WARNING,
        "Free cash flow is negative ({detail}).",
        "Free cash flow is not negative.",
        _negative_value(C.FREE_CASH_FLOW),
    ),
    _rule(
        "negative_ocf",
        Severity.CRITICAL,
        "Operating cash flow is negative ({detail}).",
        "Operating cash flow is not negative.",
        _negative_value(C.OPERATING_CASH_FLOW),
    ),
    _rule(
        "weak_liquidity",
        Severity.WARNING,
        "Current ratio below 1.0 ({detail}).",
        "Current ratio at or above 1.0.",
        _threshold("current_ratio", lambda v: v < WEAK_LIQUIDITY),
    ),
    _rule(
        "earnings_quality",
        Severity.WARNING,
        "Operating cash flow covers less than 70% of net income ({detail}).",
        "Operating cash flow adequately backs net income.",
        _earnings_quality,
    ),
    _rule(
        "reconciliation_warning",
        Severity.WARNING,
        "A reconciliation check is outside tolerance ({detail}).",
        "All reconciliation checks that could run passed.",
        _reconciliation_warning,
    ),
    _rule(
        "low_confidence_kpi",
        Severity.INFO,
        "A headline KPI is not deterministically sourced ({detail}).",
        "Revenue and net income are deterministically sourced.",
        _low_confidence_kpi,
    ),
    _rule(
        "implausible_magnitude",
        Severity.INFO,
        "A figure is implausible relative to the rest of the report ({detail}).",
        "No figure is implausibly large relative to the others.",
        _implausible_magnitude,
    ),
)


def evaluate_red_flags(
    metrics: MetricSet,
    trends: TrendSet,
    reconciliations: ReconciliationReport,
    mapping: MappingReport,
    periods: tuple[Period, ...],
    *,
    reason: Unavailable | None = None,
) -> tuple[RedFlag, ...]:
    """Every rule for the latest period. Outcome is fired, clear, or not_evaluated."""
    if not periods:
        reason = reason or Unavailable(UnavailableReason.MISSING_INPUT, "no periods detected")
        return tuple(
            RedFlag(r.rule_id, RuleOutcome.NOT_EVALUATED, r.severity, "No periods.", (), reason)
            for r in RULES
        )
    latest = max(periods)
    inputs = Inputs(metrics, trends, reconciliations, mapping, latest)
    out: list[RedFlag] = []
    for rule in RULES:
        result = rule.predicate(inputs)
        if isinstance(result, Unavailable):
            message = f"Could not evaluate: {result.root().detail}"
            out.append(
                RedFlag(
                    rule.rule_id,
                    RuleOutcome.NOT_EVALUATED,
                    rule.severity,
                    message,
                    result.refs,
                    result,
                )
            )
        elif result.fired:
            message = rule.fired_template.format(detail=result.detail)
            out.append(
                RedFlag(rule.rule_id, RuleOutcome.FIRED, rule.severity, message, result.refs)
            )
        else:
            out.append(
                RedFlag(
                    rule.rule_id, RuleOutcome.CLEAR, rule.severity, rule.clear_template, result.refs
                )
            )
    return tuple(out)
