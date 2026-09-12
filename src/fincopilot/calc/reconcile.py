"""Soft reconciliation checks. Spec 7.4.

Within tolerance -> passed. Outside, inputs present -> warning with both
sides and the delta. Inputs missing -> unavailable. There is no hard failure:
presentation rounding in a crore report routinely leaves sub-1% gaps.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

from fincopilot.calc.ratios import RATIO_CONTEXT
from fincopilot.types import CanonicalConcept as C
from fincopilot.types import (
    FinancialValue,
    MetricSet,
    Period,
    ReconciliationCheck,
    ReconciliationReport,
    ReconciliationStatus,
    StatementKind,
    Unavailable,
)

TOLERANCE_FRACTION = Decimal("0.005")  # 0.5%

ASSETS_CHECK = "assets_equal_liabilities_plus_equity"
GROSS_PROFIT_CHECK = "gross_profit_equals_revenue_minus_cogs"
FCF_CHECK = "fcf_equals_ocf_minus_capex"


def _check(
    name: str,
    period: Period,
    left: FinancialValue | Unavailable,
    right_parts: tuple[FinancialValue | Unavailable, ...],
    right_value,
    tolerance_base: FinancialValue | Unavailable,
    *,
    exact: bool,
    suspects: tuple[str, ...],
    explain: str,
) -> ReconciliationCheck:
    inputs = (left, *right_parts, tolerance_base)
    missing = [x for x in inputs if isinstance(x, Unavailable)]
    if missing:
        return ReconciliationCheck(
            name=name,
            period=period,
            status=ReconciliationStatus.UNAVAILABLE,
            left=left if isinstance(left, FinancialValue) else missing[0],
            right=missing[0],
            delta=missing[0],
            tolerance=Decimal(0),
            detail=f"cannot check: {missing[0].root().detail}",
            refs=tuple(r for x in inputs if isinstance(x, FinancialValue) for r in x.source_refs),
        )
    assert isinstance(left, FinancialValue) and isinstance(tolerance_base, FinancialValue)
    right = right_value(*(p.value for p in right_parts))  # type: ignore[union-attr]
    delta = left.value - right
    tolerance = (
        Decimal(0)
        if exact
        else RATIO_CONTEXT.multiply(abs(tolerance_base.value), TOLERANCE_FRACTION)
    )
    refs = tuple(r for x in inputs if isinstance(x, FinancialValue) for r in x.source_refs)
    if abs(delta) <= tolerance:
        status, detail = ReconciliationStatus.PASSED, f"{explain}: {left.value} vs {right}"
    else:
        status = ReconciliationStatus.WARNING
        detail = f"{explain}: {left.value} vs {right}, delta {delta} exceeds tolerance {tolerance}"
        if suspects:
            detail += f"; dash-zero cells applied on this statement: {', '.join(suspects)}"
    return ReconciliationCheck(
        name, period, status, left.value, right, delta, tolerance, detail, refs
    )


def run_reconciliations(
    metric_set: MetricSet,
    periods: tuple[Period, ...],
    dash_zero_refs: Mapping[StatementKind, tuple[str, ...]] | None = None,
) -> ReconciliationReport:
    dz = dash_zero_refs or {}
    checks: list[ReconciliationCheck] = []
    for period in sorted(set(periods), reverse=True):
        v = metric_set.value
        checks.append(
            _check(
                ASSETS_CHECK,
                period,
                v(C.TOTAL_ASSETS, period),
                (v(C.TOTAL_LIABILITIES, period), v(C.EQUITY, period)),
                lambda liabilities, equity: liabilities + equity,
                v(C.TOTAL_ASSETS, period),
                exact=False,
                suspects=dz.get(StatementKind.BALANCE, ()),
                explain="assets vs liabilities + equity",
            )
        )
        checks.append(
            _check(
                GROSS_PROFIT_CHECK,
                period,
                v(C.GROSS_PROFIT, period),
                (v(C.REVENUE, period), v(C.COGS, period)),
                lambda revenue, cogs: revenue - cogs,
                v(C.REVENUE, period),
                exact=False,
                suspects=dz.get(StatementKind.INCOME, ()),
                explain="gross profit vs revenue - cogs",
            )
        )
        checks.append(
            _check(
                FCF_CHECK,
                period,
                v(C.FREE_CASH_FLOW, period),
                (v(C.OPERATING_CASH_FLOW, period), v(C.CAPEX, period)),
                lambda ocf, capex: ocf - abs(capex),
                v(C.OPERATING_CASH_FLOW, period),
                exact=True,
                suspects=dz.get(StatementKind.CASH_FLOW, ()),
                explain="fcf vs ocf - |capex|",
            )
        )
    return ReconciliationReport(tuple(checks))
