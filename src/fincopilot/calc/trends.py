"""Year-over-year changes between ADJACENT periods only. Spec 7.3.

Direction and economic sense are decided here, in Python. A narrative model
downstream receives the label and never derives it.
"""

from __future__ import annotations

from decimal import Decimal

from fincopilot.calc.ratios import RATIO_CONTEXT
from fincopilot.types import (
    CanonicalConcept as C,
)
from fincopilot.types import (
    Direction,
    EconomicSense,
    Maybe,
    MetricSet,
    Period,
    Trend,
    TrendSet,
    Unavailable,
    UnavailableReason,
)

# What a RISE means for the business. Falls invert; flat is neutral.
RISE_IS: dict[str, EconomicSense] = {
    C.REVENUE.value: EconomicSense.POSITIVE,
    C.GROSS_PROFIT.value: EconomicSense.POSITIVE,
    C.OPERATING_INCOME.value: EconomicSense.POSITIVE,
    C.NET_INCOME.value: EconomicSense.POSITIVE,
    C.EBITDA.value: EconomicSense.POSITIVE,
    C.OPERATING_CASH_FLOW.value: EconomicSense.POSITIVE,
    C.FREE_CASH_FLOW.value: EconomicSense.POSITIVE,
    C.TOTAL_DEBT.value: EconomicSense.NEGATIVE,
    C.CASH.value: EconomicSense.POSITIVE,
    C.EQUITY.value: EconomicSense.POSITIVE,
    "gross_margin": EconomicSense.POSITIVE,
    "operating_margin": EconomicSense.POSITIVE,
    "net_margin": EconomicSense.POSITIVE,
    "current_ratio": EconomicSense.POSITIVE,
    "debt_to_equity": EconomicSense.NEGATIVE,
    "roa": EconomicSense.POSITIVE,
    "roe": EconomicSense.POSITIVE,
}

_INVERT = {
    EconomicSense.POSITIVE: EconomicSense.NEGATIVE,
    EconomicSense.NEGATIVE: EconomicSense.POSITIVE,
    EconomicSense.NEUTRAL: EconomicSense.NEUTRAL,
}


def yoy(subject: str, earlier: Decimal, later: Decimal, from_p: Period, to_p: Period) -> Trend:
    change = later - earlier
    if change > 0:
        direction, economic = Direction.UP, RISE_IS.get(subject, EconomicSense.NEUTRAL)
    elif change < 0:
        direction = Direction.DOWN
        economic = _INVERT[RISE_IS.get(subject, EconomicSense.NEUTRAL)]
    else:
        direction, economic = Direction.FLAT, EconomicSense.NEUTRAL
    relative: Maybe[Decimal]
    if earlier == 0:
        relative = Unavailable(
            UnavailableReason.DIVISION_BY_ZERO, f"{subject}: prior period is zero"
        )
    else:
        relative = RATIO_CONTEXT.divide(change, abs(earlier))
    return Trend(subject, from_p, to_p, change, relative, direction, economic)


def calculate_trends(metric_set: MetricSet, periods: tuple[Period, ...]) -> TrendSet:
    ordered = tuple(sorted(set(periods), reverse=True))
    trends: list[Trend] = []
    unavailable: dict[tuple[str, Period], Unavailable] = {}

    def add(subject: str, to_p: Period, from_p: Period, later, earlier):
        causes = [x for x in (later, earlier) if isinstance(x, Unavailable)]
        if causes:
            unavailable[(subject, to_p)] = Unavailable(
                UnavailableReason.MISSING_INPUT,
                f"{subject} change {from_p.end_year}->{to_p.end_year}: {causes[0].detail}",
                refs=causes[0].refs,
                cause=causes[0],
            )
            return
        trends.append(yoy(subject, earlier.value, later.value, from_p, to_p))

    for i in range(len(ordered) - 1):
        to_p, from_p = ordered[i], ordered[i + 1]
        for subject in RISE_IS:
            if subject in {c.value for c in C}:
                concept = C(subject)
                add(
                    subject,
                    to_p,
                    from_p,
                    metric_set.value(concept, to_p),
                    metric_set.value(concept, from_p),
                )
            else:
                add(
                    subject,
                    to_p,
                    from_p,
                    metric_set.metric(subject, to_p),
                    metric_set.metric(subject, from_p),
                )

    return TrendSet(trends=tuple(trends), unavailable=unavailable)
