"""Stage orchestration only. Spec 2.2, 2.3.

No Streamlit, no database, no direct Ollama calls, no financial logic. Every
stage takes a contract in and returns a contract out. The only external I/O
after extract_pdf is the injected LLM client, and it is optional: with
llm=None or NullMapper the pipeline performs no I/O at all after extraction.
"""

from __future__ import annotations

from fincopilot.ai.client import LLMClient
from fincopilot.ai.llm_map import fill_unmapped
from fincopilot.ai.narrative import generate_narrative
from fincopilot.calc.ratios import calculate_metrics
from fincopilot.calc.reconcile import run_reconciliations
from fincopilot.calc.trends import calculate_trends
from fincopilot.extract.locate import locate_statements
from fincopilot.extract.pdf import DEFAULT_MAX_BYTES, DEFAULT_MAX_PAGES, extract_pdf, validate_input
from fincopilot.extract.periods import detect_periods, reconcile_fiscal_years
from fincopilot.extract.units import normalize_document
from fincopilot.mapping.synonyms import map_rows
from fincopilot.mapping.validate import validate_mappings
from fincopilot.rules.redflags import evaluate_red_flags
from fincopilot.types import (
    AnalysisResult,
    Narrative,
    NormalizedCell,
    NormalizedTable,
    NormalizedTables,
    PeriodMap,
    StatementKind,
    Unavailable,
)


def _dash_zero_refs(normalized: NormalizedTables) -> dict[StatementKind, tuple[str, ...]]:
    out: dict[StatementKind, tuple[str, ...]] = {}
    for t in (normalized.income, normalized.balance, normalized.cash_flow):
        if isinstance(t, NormalizedTable):
            refs = tuple(
                dict.fromkeys(
                    ref_id
                    for (ref_id, _), cell in t.cells.items()
                    if isinstance(cell, NormalizedCell) and cell.dash_zero
                )
            )
            if refs:
                out[t.kind] = refs
    return out


def analyze(
    data: bytes,
    *,
    llm: LLMClient | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> AnalysisResult:
    """bytes -> AnalysisResult. Raises IngestionError subclasses at the gate only."""
    ref = validate_input(data, max_bytes=max_bytes)
    doc = extract_pdf(data, ref, max_pages=max_pages)
    statements = locate_statements(doc)
    periods = reconcile_fiscal_years(statements, detect_periods(statements), doc.page_text)
    normalized = normalize_document(statements, periods, doc)

    mappings = map_rows(normalized)
    if llm is not None:
        mappings = fill_unmapped(mappings, normalized, doc.refs, llm)

    period_map = periods if isinstance(periods, PeriodMap) else PeriodMap(columns={}, ordered=())
    mapping = validate_mappings(mappings, normalized, period_map)
    ordered = period_map.ordered

    metric_set = calculate_metrics(mapping, ordered)
    trend_set = calculate_trends(metric_set, ordered)
    reconciliation = run_reconciliations(metric_set, ordered, _dash_zero_refs(normalized))
    cause = periods if isinstance(periods, Unavailable) else None
    red_flags = evaluate_red_flags(
        metric_set, trend_set, reconciliation, mapping, ordered, reason=cause
    )

    return AnalysisResult(
        document_id=doc.document_id,
        statements=statements,
        periods=periods,
        values=metric_set.values,
        metrics=metric_set.metrics,
        trends=trend_set.trends,
        reconciliations=reconciliation.checks,
        red_flags=red_flags,
        mapping=mapping,
        metric_set=metric_set,
        trend_set=trend_set,
        reconciliation_report=reconciliation,
    )


def narrate(result: AnalysisResult, llm: LLMClient) -> Narrative | Unavailable:
    """Phase 9. Separate from analyze() on purpose: the deterministic result is
    complete before any model runs, and stays untouched whatever the model does."""
    return generate_narrative(result, llm)
