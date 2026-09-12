"""Derived values and ratio metrics. Spec 7.1, 7.2.

Pure functions over a MappingReport. Decimal end to end; every division
runs in RATIO_CONTEXT so results are reproducible to the digit. Quantise only
at display, never here.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Context, Decimal, Inexact

from fincopilot.types import (
    AnalyticalConfidence,
    FinancialValue,
    MappingReport,
    Maybe,
    Metric,
    MetricSet,
    MetricUnit,
    Period,
    Unavailable,
    UnavailableReason,
)
from fincopilot.types import (
    CanonicalConcept as C,
)

# Phase 6 owns ratio precision: 34 significant digits (IEEE decimal128),
# banker's rounding. Golden tests assert against this exact context.
RATIO_CONTEXT = Context(prec=34, rounding=ROUND_HALF_EVEN)

# Sums and differences of document figures must be exact or refuse. The
# default 28-digit context would round silently; this one traps.
EXACT_CONTEXT = Context(prec=400, traps=[Inexact])

_RANK = {AnalyticalConfidence.LOW: 0, AnalyticalConfidence.MEDIUM: 1, AnalyticalConfidence.HIGH: 2}


def _min_confidence(*values: FinancialValue) -> AnalyticalConfidence:
    return min((v.analytical_confidence for v in values), key=_RANK.__getitem__)


def _missing(name: str, period: Period, *causes: Unavailable) -> Unavailable:
    cause = causes[0] if causes else None
    return Unavailable(
        UnavailableReason.MISSING_INPUT,
        f"{name} {period.end_year}: {cause.detail if cause else 'input missing'}",
        refs=tuple(r for c in causes for r in c.refs),
        cause=cause,
    )


# --- derived values ---------------------------------------------------------


def _derive(
    concept: C,
    period: Period,
    report: MappingReport,
    inputs: tuple[C, ...],
    combine,
) -> Maybe[FinancialValue]:
    """Direct mapping wins. Otherwise derive only when EVERY input is present."""
    direct = report.get(concept, period)
    if isinstance(direct, FinancialValue):
        return direct
    found = [report.get(c, period) for c in inputs]
    causes = [f for f in found if isinstance(f, Unavailable)]
    if causes:
        return _missing(concept.value, period, *causes)
    vals: list[FinancialValue] = found  # type: ignore[assignment]
    currencies = {v.currency for v in vals}
    if len(currencies) != 1:
        return Unavailable(
            UnavailableReason.CONFLICT,
            f"{concept.value} {period.end_year}: inputs in different currencies {currencies}",
            refs=tuple(r for v in vals for r in v.source_refs),
        )
    try:
        value = combine(*(v.value for v in vals))
    except Inexact:
        return Unavailable(
            UnavailableReason.UNPARSEABLE,
            f"{concept.value} {period.end_year}: inputs exceed exact precision",
            refs=tuple(r for v in vals for r in v.source_refs),
        )
    return FinancialValue.derived(
        concept=concept,
        period=period,
        value=value,
        currency=vals[0].currency,
        derived_from=tuple(c.value for c in inputs),
        analytical_confidence=_min_confidence(*vals),
    )


def derive_total_debt(report: MappingReport, period: Period) -> Maybe[FinancialValue]:
    return _derive(
        C.TOTAL_DEBT,
        period,
        report,
        (C.SHORT_TERM_BORROWINGS, C.LONG_TERM_BORROWINGS),
        lambda st, lt: EXACT_CONTEXT.add(st, lt),
    )


def derive_free_cash_flow(report: MappingReport, period: Period) -> Maybe[FinancialValue]:
    # capex is normalised to its positive magnitude first (spec 7.2).
    return _derive(
        C.FREE_CASH_FLOW,
        period,
        report,
        (C.OPERATING_CASH_FLOW, C.CAPEX),
        lambda ocf, capex: EXACT_CONTEXT.subtract(ocf, abs(capex)),
    )


def derive_ebitda(report: MappingReport, period: Period) -> Maybe[FinancialValue]:
    return _derive(
        C.EBITDA,
        period,
        report,
        (C.OPERATING_INCOME, C.D_AND_A),
        lambda oi, da: EXACT_CONTEXT.add(oi, da),
    )


# --- ratios -----------------------------------------------------------------


def _ratio(
    name: str,
    period: Period,
    numerator: Maybe[FinancialValue],
    denominator: Maybe[FinancialValue],
    *,
    unit: MetricUnit = MetricUnit.RATIO,
) -> Maybe[Metric]:
    causes = [x for x in (numerator, denominator) if isinstance(x, Unavailable)]
    for cause in causes:
        # "Not meaningful" is a verdict about this ratio, not a missing input.
        if cause.reason is UnavailableReason.AMBIGUOUS:
            return cause
    if causes:
        return _missing(name, period, *causes)
    assert isinstance(numerator, FinancialValue) and isinstance(denominator, FinancialValue)
    if denominator.value == 0:
        return Unavailable(
            UnavailableReason.DIVISION_BY_ZERO,
            f"{name} {period.end_year}: {denominator.concept.value} is zero",
            refs=denominator.source_refs,
        )
    return Metric(
        name=name,
        period=period,
        value=RATIO_CONTEXT.divide(numerator.value, denominator.value),
        unit=unit,
        inputs=numerator.source_refs + denominator.source_refs,
        analytical_confidence=_min_confidence(numerator, denominator),
    )


def _margin(name: str, period: Period, num: Maybe[FinancialValue], revenue: Maybe[FinancialValue]):
    if isinstance(revenue, FinancialValue) and revenue.value < 0:
        return Unavailable(
            UnavailableReason.AMBIGUOUS,
            f"{name} {period.end_year}: revenue is negative; margin not meaningful",
            refs=revenue.source_refs,
        )
    return _ratio(name, period, num, revenue, unit=MetricUnit.PERCENT)


def ocf_to_net_income(
    ocf: Maybe[FinancialValue], net_income: Maybe[FinancialValue], period: Period
) -> Maybe[Metric]:
    """Cash backing of profit. Meaningless against a loss: -100 / -50 reads as +2."""
    if isinstance(net_income, FinancialValue) and net_income.value <= 0:
        return Unavailable(
            UnavailableReason.AMBIGUOUS,
            f"ocf_to_net_income {period.end_year}: net income is not positive; "
            "ratio not meaningful",
            refs=net_income.source_refs,
        )
    return _ratio("ocf_to_net_income", period, ocf, net_income)


def debt_to_equity(debt: Maybe[FinancialValue], equity: Maybe[FinancialValue], period: Period):
    if isinstance(equity, FinancialValue) and equity.value < 0:
        return Unavailable(
            UnavailableReason.AMBIGUOUS,
            f"debt_to_equity {period.end_year}: equity is negative; ratio not meaningful",
            refs=equity.source_refs,
        )
    return _ratio("debt_to_equity", period, debt, equity)


def _average_denominator(
    name: str, concept: C, period: Period, prior: Period | None, report: MappingReport
) -> Maybe[FinancialValue]:
    """ROA/ROE need two balance sheets. One period is never substituted."""
    current = report.get(concept, period)
    if isinstance(current, Unavailable):
        return current
    if prior is None:
        return Unavailable(
            UnavailableReason.MISSING_INPUT,
            f"{name} {period.end_year}: prior-period {concept.value} required for average",
            refs=current.source_refs,
        )
    previous = report.get(concept, prior)
    if isinstance(previous, Unavailable):
        return Unavailable(
            UnavailableReason.MISSING_INPUT,
            f"{name} {period.end_year}: prior-period {concept.value} required for average",
            refs=current.source_refs,
            cause=previous,
        )
    if current.currency != previous.currency:
        return Unavailable(UnavailableReason.CONFLICT, f"{name}: currency differs across periods")
    average = RATIO_CONTEXT.divide(EXACT_CONTEXT.add(current.value, previous.value), Decimal(2))
    if average < 0:
        # Two negatives cancel: a loss over negative equity would read as a
        # tidy positive return. Same analytical trap as debt-to-equity.
        return Unavailable(
            UnavailableReason.AMBIGUOUS,
            f"{name} {period.end_year}: average {concept.value} is negative; ratio not meaningful",
            refs=current.source_refs + previous.source_refs,
        )
    return FinancialValue.derived(
        concept=concept,
        period=period,
        value=average,
        currency=current.currency,
        derived_from=(f"{concept.value}_{period.end_year}", f"{concept.value}_{prior.end_year}"),
        analytical_confidence=_min_confidence(current, previous),
    )


# --- the stage ----------------------------------------------------------------

METRIC_NAMES = (
    "gross_margin",
    "operating_margin",
    "net_margin",
    "ebitda_margin",
    "current_ratio",
    "debt_to_equity",
    "roa",
    "roe",
    "ocf_to_net_income",
)


def calculate_metrics(report: MappingReport, periods: tuple[Period, ...]) -> MetricSet:
    """Every formula for every period. Absent results carry their root cause."""
    ordered = tuple(sorted(set(periods), reverse=True))
    values: list[FinancialValue] = list(report.values)
    metrics: list[Metric] = []
    # Mapping-level reasons (unparseable cell, blank, conflict) travel with the set.
    unavailable: dict[tuple[str, Period], Unavailable] = {
        (concept.value, period): why for (concept, period), why in report.unavailable.items()
    }

    def keep(name: str, period: Period, result):
        if isinstance(result, Unavailable):
            unavailable[(name, period)] = result
        elif isinstance(result, Metric):
            metrics.append(result)
        elif result.derived_from is not None and result not in values:
            values.append(result)

    for i, period in enumerate(ordered):
        prior = ordered[i + 1] if i + 1 < len(ordered) else None
        debt = derive_total_debt(report, period)
        fcf = derive_free_cash_flow(report, period)
        ebitda = derive_ebitda(report, period)
        for concept, result in ((C.TOTAL_DEBT, debt), (C.FREE_CASH_FLOW, fcf), (C.EBITDA, ebitda)):
            keep(concept.value, period, result)

        revenue = report.get(C.REVENUE, period)
        keep(
            "gross_margin",
            period,
            _margin("gross_margin", period, report.get(C.GROSS_PROFIT, period), revenue),
        )
        keep(
            "operating_margin",
            period,
            _margin("operating_margin", period, report.get(C.OPERATING_INCOME, period), revenue),
        )
        keep(
            "net_margin",
            period,
            _margin("net_margin", period, report.get(C.NET_INCOME, period), revenue),
        )
        keep("ebitda_margin", period, _margin("ebitda_margin", period, ebitda, revenue))
        keep(
            "current_ratio",
            period,
            _ratio(
                "current_ratio",
                period,
                report.get(C.CURRENT_ASSETS, period),
                report.get(C.CURRENT_LIABILITIES, period),
            ),
        )
        keep("debt_to_equity", period, debt_to_equity(debt, report.get(C.EQUITY, period), period))
        keep(
            "roa",
            period,
            _ratio(
                "roa",
                period,
                report.get(C.NET_INCOME, period),
                _average_denominator("roa", C.TOTAL_ASSETS, period, prior, report),
            ),
        )
        keep(
            "roe",
            period,
            _ratio(
                "roe",
                period,
                report.get(C.NET_INCOME, period),
                _average_denominator("roe", C.EQUITY, period, prior, report),
            ),
        )
        keep(
            "ocf_to_net_income",
            period,
            ocf_to_net_income(
                report.get(C.OPERATING_CASH_FLOW, period),
                report.get(C.NET_INCOME, period),
                period,
            ),
        )

    return MetricSet(values=tuple(values), metrics=tuple(metrics), unavailable=unavailable)
