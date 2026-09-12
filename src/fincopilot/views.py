"""Rows and cards for the dashboard. Pure functions over AnalysisResult.

No Streamlit here, so every table the UI shows is testable. Every row carries
a `status`: 'ok' (verified), 'low' (usable, lower confidence), 'warning',
or 'na' (not available, with the reason). The UI must render these
distinctly; the rule lives here so the UI cannot forget it.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from fincopilot.display import (
    confidence_text,
    format_metric,
    metric_text,
    relative_text,
    unavailable_text,
    value_text,
)
from fincopilot.types import (
    AnalysisResult,
    AnalyticalConfidence,
    ExtractionConfidence,
    MetricUnit,
    ReconciliationStatus,
    StatementBasis,
    Unavailable,
)

KPI_ORDER = (
    "net_margin",
    "operating_margin",
    "current_ratio",
    "debt_to_equity",
    "roe",
    "ocf_to_net_income",
)
KPI_LABEL = {
    "net_margin": "Net margin",
    "operating_margin": "Operating margin",
    "gross_margin": "Gross margin",
    "ebitda_margin": "EBITDA margin",
    "current_ratio": "Current ratio",
    "debt_to_equity": "Debt to equity",
    "roe": "Return on equity",
    "roa": "Return on assets",
    "ocf_to_net_income": "Cash backing of profit",
}


CONCEPT_LABEL = {
    "revenue": "Revenue",
    "cogs": "Cost of sales",
    "gross_profit": "Gross profit",
    "operating_income": "Operating income",
    "d_and_a": "Depreciation and amortisation",
    "ebitda": "EBITDA",
    "net_income": "Net income",
    "total_assets": "Total assets",
    "current_assets": "Current assets",
    "cash": "Cash and equivalents",
    "total_liabilities": "Total liabilities",
    "current_liabilities": "Current liabilities",
    "short_term_borrowings": "Short-term borrowings",
    "long_term_borrowings": "Long-term borrowings",
    "total_debt": "Total debt",
    "equity": "Equity",
    "operating_cash_flow": "Operating cash flow",
    "capex": "Capital expenditure",
    "free_cash_flow": "Free cash flow",
}


@dataclass(frozen=True, slots=True)
class Kpi:
    name: str
    label: str
    period: int
    value: str  # display text or "N/A"
    delta: str  # "+1.2%" vs prior period, or ""
    delta_reads: str  # positive | negative | neutral (economic sense, not sign)
    status: str  # ok | low | na
    note: str  # reason when na, confidence text otherwise


@dataclass(frozen=True, slots=True)
class Notice:
    level: str  # info | warning | error
    text: str


def _status(conf: AnalyticalConfidence) -> str:
    return "ok" if conf is AnalyticalConfidence.HIGH else "low"


def _card_note(u: Unavailable, name: str, period: int) -> str:
    """The reason, trimmed of what the card already says: the N/A marker and
    the metric's own name and year."""
    text = unavailable_text(u).removeprefix("N/A - ")
    return text.replace(f"{name} {period}: ", "")


def basis_notice(result: AnalysisResult) -> Notice:
    b = result.basis
    if b is StatementBasis.CONSOLIDATED:
        return Notice("info", "Consolidated statements (group as a whole).")
    if b is StatementBasis.STANDALONE_FALLBACK:
        return Notice(
            "warning",
            "No consolidated statements found. Showing STANDALONE figures, which cover "
            "the parent entity only and can differ materially from the group.",
        )
    return Notice(
        "error",
        "Statement basis could not be determined. Figures come from tables located by "
        "keyword scoring alone. Treat every number below as low confidence.",
    )


def period_notice(result: AnalysisResult) -> Notice | None:
    if isinstance(result.periods, Unavailable):
        return Notice("error", f"Periods: {unavailable_text(result.periods)}")
    return None


def kpi_cards(result: AnalysisResult) -> list[Kpi]:
    if isinstance(result.periods, Unavailable) or not result.periods.ordered:
        return []
    latest = result.periods.ordered[0]  # newest first
    cards: list[Kpi] = []
    for name in KPI_ORDER:
        m = result.metric_set.metric(name, latest)
        if isinstance(m, Unavailable):
            cards.append(
                Kpi(
                    name,
                    KPI_LABEL[name],
                    latest.end_year,
                    "N/A",
                    "",
                    "neutral",
                    "na",
                    _card_note(m, name, latest.end_year),
                )
            )
            continue
        t = result.trend_set.get(name, latest)
        has_trend = t is not None and not isinstance(t, Unavailable)
        delta = relative_text(t.relative_change) if has_trend else ""
        reads = t.economic.value if has_trend else "neutral"
        conf = (
            "high confidence"
            if m.analytical_confidence is AnalyticalConfidence.HIGH
            else (f"{m.analytical_confidence.value} confidence")
        )
        cards.append(
            Kpi(
                name,
                KPI_LABEL[name],
                latest.end_year,
                metric_text(m),
                delta,
                reads,
                _status(m.analytical_confidence),
                conf,
            )
        )
    return cards


def value_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    rows = []
    for v in result.values:
        rows.append(
            {
                "concept": CONCEPT_LABEL.get(v.concept.value, v.concept.value),
                "period": v.period.end_year,
                "value": value_text(v),
                "page": v.source_page if v.cell else "",
                "source_row": v.source_label
                if v.cell
                else "derived from "
                + ", ".join(CONCEPT_LABEL.get(d, d).lower() for d in (v.derived_from or ())),
                "how_found": confidence_text(v),
                "ref_id": v.cell.ref.ref_id if v.cell else "",
                "status": "low"
                if v.extraction_confidence is ExtractionConfidence.LLM_MAPPED
                or v.analytical_confidence is not AnalyticalConfidence.HIGH
                else "ok",
            }
        )
    return rows


def metric_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    rows = [
        {
            "metric": KPI_LABEL.get(m.name, m.name),
            "period": m.period.end_year,
            "value": metric_text(m),
            "inputs": ", ".join(m.inputs),
            "status": _status(m.analytical_confidence),
        }
        for m in result.metrics
    ]
    rows += [
        {
            "metric": KPI_LABEL.get(name, name),
            "period": period.end_year,
            "value": unavailable_text(u),
            "inputs": "",
            "status": "na",
        }
        for (name, period), u in result.metric_set.unavailable.items()
        if name in KPI_LABEL
    ]
    return sorted(rows, key=lambda r: (r["metric"], r["period"]))


def trend_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    return [
        {
            "subject": KPI_LABEL.get(t.subject) or CONCEPT_LABEL.get(t.subject, t.subject),
            "from": t.from_period.end_year,
            "to": t.to_period.end_year,
            "change": relative_text(t.relative_change),
            "direction": t.direction.value,
            "reads_as": t.economic.value,
            "status": "ok" if not isinstance(t.relative_change, Unavailable) else "na",
        }
        for t in result.trends
    ]


def reconciliation_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    return [
        {
            "check": c.name.replace("_", " "),
            "period": c.period.end_year,
            "status": c.status.value,
            "detail": c.detail,
            "refs": ", ".join(c.refs),
        }
        for c in result.reconciliations
    ]


def red_flag_rows(result: AnalysisResult) -> list[dict[str, Any]]:
    return [
        {
            "rule": f.rule_id.replace("_", " "),
            "status": f.outcome.value,
            "severity": f.severity.value,
            "message": f.message,
            "refs": ", ".join(f.refs),
        }
        for f in result.red_flags
    ]


def provenance(result: AnalysisResult, ref_id: str) -> dict[str, Any] | None:
    """Walk the chain back to the cell. Only mapped values have one."""
    for v in result.values:
        if v.cell and v.cell.ref.ref_id == ref_id:
            ref = v.cell.ref
            return {
                "ref_id": ref.ref_id,
                "page": ref.page,
                "table": ref.table_idx,
                "row": ref.row_idx,
                "column": ref.col_idx,
                "row_label": ref.row_label,
                "raw_text": v.cell.raw_token,
                "scale": f"{v.cell.scale.value} ({v.cell.scale_source.value})",
                "currency": v.cell.currency,
                "value_in_base_units": str(v.value),
                "dash_zero": v.cell.dash_zero,
                "concept": CONCEPT_LABEL.get(v.concept.value, v.concept.value),
                "period": v.period.end_year,
            }
    return None


def history_metric_rows(rows) -> list[dict[str, Any]]:
    """Stored metrics (store.MetricRow) formatted like live ones. Decimal text in, display out."""
    out = []
    for r in rows:
        try:
            shown = format_metric(Decimal(r.value), MetricUnit(r.unit))
        except (InvalidOperation, ValueError):
            shown = r.value
        out.append(
            {
                "metric": KPI_LABEL.get(r.name, r.name),
                "period": r.period,
                "value": shown,
                "status": "ok" if r.analytical_confidence == "high" else "low",
            }
        )
    return out


def warning_count(result: AnalysisResult) -> int:
    return sum(1 for c in result.reconciliations if c.status is ReconciliationStatus.WARNING)
