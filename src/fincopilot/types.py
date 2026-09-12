"""Domain contracts for Finance Copilot.

Every type here is frozen. Every enum is a closed set. Unavailability is a
type, not a convention: see `Unavailable`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Any


class UnavailableReason(Enum):
    """Closed set. Do not extend without a spec change."""

    MISSING_INPUT = "missing_input"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    UNPARSEABLE = "unparseable"
    NOT_LOCATED = "not_located"
    DIVISION_BY_ZERO = "division_by_zero"


@dataclass(frozen=True, slots=True)
class Unavailable:
    """A value that could not be determined, and why.

    Never substitute None, 0, NaN, or inf for financial data. `cause` chains
    to the upstream failure so the UI can report the root cause, which is the
    only part a user can act on.
    """

    reason: UnavailableReason
    detail: str
    refs: tuple[str, ...] = ()
    cause: Unavailable | None = None

    def root(self) -> Unavailable:
        """The deepest cause in the chain. Returns self when there is none."""
        node = self
        while node.cause is not None:
            node = node.cause
        return node


type Maybe[T] = T | Unavailable
"""A value, or an explicit explanation of its absence. PEP 695, Python 3.12+."""


def is_unavailable(value: Any) -> bool:
    """Narrow a `Maybe`. Prefer this over bare isinstance at call sites."""
    return isinstance(value, Unavailable)


class ExtractionConfidence(Enum):
    """How the value's source row was identified."""

    EXACT_MATCH = "exact_match"  # literal canonical label
    SYNONYM_MATCH = "synonym_match"  # curated alias hit
    LLM_MAPPED = "llm_mapped"  # model picked the row; Python took the number
    UNMAPPED = "unmapped"


class AnalyticalConfidence(Enum):
    """How much weight the analysis deserves. Independent of extraction."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Scale(Enum):
    """Presentation scale declared by the report, e.g. "(Rs. in crore)"."""

    UNIT = "unit"
    THOUSAND = "thousand"
    LAKH = "lakh"
    MILLION = "million"
    CRORE = "crore"
    BILLION = "billion"


SCALE_MULTIPLIER: dict[Scale, Decimal] = {
    Scale.UNIT: Decimal(1),
    Scale.THOUSAND: Decimal(1_000),
    Scale.LAKH: Decimal(100_000),
    Scale.MILLION: Decimal(1_000_000),
    Scale.CRORE: Decimal(10_000_000),
    Scale.BILLION: Decimal(1_000_000_000),
}


class ScaleSource(Enum):
    """Where the scale was discovered. Resolution order: cell, table, statement, document."""

    CELL = "cell"
    TABLE = "table"
    STATEMENT = "statement"
    DOCUMENT = "document"


def make_ref_id(page: int, table_idx: int, row_idx: int) -> str:
    """The one place document-local row IDs are formatted."""
    return f"page_{page}_table_{table_idx}_row_{row_idx}"


@dataclass(frozen=True, slots=True)
class SourceRef:
    """A pointer into the extracted document.

    Only `fincopilot.extract` may construct these. It builds them while walking
    the extracted structure, so existence is true by construction and needs no
    later verification. `page` is always the TRUE page, preserved across
    multi-page statement stitching.
    """

    ref_id: str
    document_id: str
    page: int
    table_idx: int
    row_idx: int
    col_idx: int | None
    row_label: str
    raw_text: str


@dataclass(frozen=True, slots=True)
class NormalizedCell:
    """A parsed numeric cell. `value` is in base units; scale is kept for display."""

    ref: SourceRef
    raw_token: str
    value: Decimal
    scale: Scale
    scale_source: ScaleSource
    currency: str  # "INR", "USD"
    dash_zero: bool = False


class StatementKind(Enum):
    INCOME = "income"
    BALANCE = "balance"
    CASH_FLOW = "cash_flow"


class StatementBasis(Enum):
    """Decided by evidence, never assumption.

    UNKNOWN proceeds with a label rather than blocking — refusing to analyse an
    unlabelled statement would reject every single-entity company.
    """

    CONSOLIDATED = "consolidated"
    STANDALONE_FALLBACK = "standalone_fallback"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class TableRow:
    ref: SourceRef
    label: str
    cells: tuple[str, ...]  # raw cell text, one per column, header order


@dataclass(frozen=True, slots=True)
class ExtractedTable:
    """One logical table. May span several pages after stitching."""

    table_id: str
    first_page: int
    pages: tuple[int, ...]
    header: tuple[str, ...]
    rows: tuple[TableRow, ...]
    caption: str | None
    col_x: tuple[float, ...] = ()  # left edge of each column in PDF points; stitching input


@dataclass(frozen=True, slots=True)
class RawDocument:
    """Everything extraction found. `refs` is the only authority on row existence."""

    document_id: str
    page_count: int
    page_text: tuple[str, ...]
    tables: tuple[ExtractedTable, ...]
    refs: Mapping[str, SourceRef]


@dataclass(frozen=True, slots=True)
class Statement:
    kind: StatementKind
    basis: StatementBasis
    table: ExtractedTable


@dataclass(frozen=True, slots=True)
class StatementSet:
    """A missing statement is Unavailable, not fatal. The others still analyse."""

    basis: StatementBasis
    income: Maybe[Statement]
    balance: Maybe[Statement]
    cash_flow: Maybe[Statement]


@dataclass(frozen=True, slots=True)
class ResolvedScale:
    """A scale and the level of the hierarchy it was discovered at."""

    scale: Scale
    source: ScaleSource


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    """One statement with every period cell parsed to base units.

    `cells` is keyed by (row ref_id, column index). A blank, unparseable, or
    unscaled cell is an Unavailable, never a number.
    """

    kind: StatementKind
    basis: StatementBasis
    table: ExtractedTable
    scale: ResolvedScale
    currency: str
    cells: Mapping[tuple[str, int], Maybe[NormalizedCell]]


@dataclass(frozen=True, slots=True)
class NormalizedTables:
    income: Maybe[NormalizedTable]
    balance: Maybe[NormalizedTable]
    cash_flow: Maybe[NormalizedTable]


@dataclass(frozen=True, slots=True, order=True)
class Period:
    """A reporting period, identified by the year it ends.

    Indian fiscal years normalise to their ending year: "FY 2023-24" -> 2024.
    `label` keeps the report's own wording and is excluded from comparison, so
    two columns that resolve to the same period compare equal — which is how
    Phase 3 detects an AMBIGUOUS period map.
    """

    end_year: int
    label: str = field(compare=False)


@dataclass(frozen=True, slots=True)
class PeriodMap:
    """Column-to-period resolution, keyed per statement.

    Statements in one report routinely carry different period counts: a 10-K
    shows three years of operations against two balance sheets.
    """

    columns: Mapping[tuple[StatementKind, int], Period]
    ordered: tuple[Period, ...]  # document-wide union, newest first

    def periods_for(self, kind: StatementKind) -> tuple[Period, ...]:
        """Periods available on one statement, newest first. Empty when absent."""
        found = {p for (k, _), p in self.columns.items() if k is kind}
        return tuple(sorted(found, reverse=True))


class CanonicalConcept(Enum):
    """Closed vocabulary. `d_and_a` exists so EBITDA can be derived."""

    REVENUE = "revenue"
    GROSS_PROFIT = "gross_profit"
    COGS = "cogs"
    OPERATING_INCOME = "operating_income"
    D_AND_A = "d_and_a"
    EBITDA = "ebitda"
    NET_INCOME = "net_income"
    TOTAL_ASSETS = "total_assets"
    CURRENT_ASSETS = "current_assets"
    CASH = "cash"
    TOTAL_LIABILITIES = "total_liabilities"
    CURRENT_LIABILITIES = "current_liabilities"
    SHORT_TERM_BORROWINGS = "short_term_borrowings"
    LONG_TERM_BORROWINGS = "long_term_borrowings"
    TOTAL_DEBT = "total_debt"
    EQUITY = "equity"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    CAPEX = "capex"
    FREE_CASH_FLOW = "free_cash_flow"


_CONFIDENCE_RANK: dict[AnalyticalConfidence, int] = {
    AnalyticalConfidence.LOW: 0,
    AnalyticalConfidence.MEDIUM: 1,
    AnalyticalConfidence.HIGH: 2,
}


@dataclass(frozen=True, slots=True)
class FinancialValue:
    """One canonical concept, for one period, with its provenance.

    Exactly one of `cell` (mapped from a document row) or `derived_from`
    (computed from other concepts) is set. A mapped value's number must equal
    its cell's number: that equality is the enforcement point for "the document
    is the source of truth".

    Prefer the `from_cell` and `derived` constructors over calling this directly.
    """

    concept: CanonicalConcept
    period: Period
    value: Decimal
    currency: str
    extraction_confidence: ExtractionConfidence
    analytical_confidence: AnalyticalConfidence
    cell: NormalizedCell | None
    derived_from: tuple[str, ...] | None

    def __post_init__(self) -> None:
        if (self.cell is None) == (self.derived_from is None):
            raise ValueError(
                "FinancialValue needs exactly one of cell or derived_from; "
                f"got cell={self.cell!r}, derived_from={self.derived_from!r}"
            )
        if self.cell is not None and self.value != self.cell.value:
            raise ValueError(
                "a mapped FinancialValue must equal its cell value: "
                f"{self.value} != {self.cell.value} at {self.cell.ref.ref_id}"
            )

    @classmethod
    def from_cell(
        cls,
        *,
        concept: CanonicalConcept,
        period: Period,
        cell: NormalizedCell,
        extraction_confidence: ExtractionConfidence,
        analytical_confidence: AnalyticalConfidence,
    ) -> FinancialValue:
        """Build from a document row. LLM-mapped values are capped at MEDIUM."""
        if extraction_confidence is ExtractionConfidence.LLM_MAPPED:
            analytical_confidence = min(
                analytical_confidence,
                AnalyticalConfidence.MEDIUM,
                key=_CONFIDENCE_RANK.__getitem__,
            )
        return cls(
            concept=concept,
            period=period,
            value=cell.value,
            currency=cell.currency,
            extraction_confidence=extraction_confidence,
            analytical_confidence=analytical_confidence,
            cell=cell,
            derived_from=None,
        )

    @classmethod
    def derived(
        cls,
        *,
        concept: CanonicalConcept,
        period: Period,
        value: Decimal,
        currency: str,
        derived_from: tuple[str, ...],
        analytical_confidence: AnalyticalConfidence,
    ) -> FinancialValue:
        """Build from other concepts, e.g. EBITDA from operating income + D&A."""
        return cls(
            concept=concept,
            period=period,
            value=value,
            currency=currency,
            extraction_confidence=ExtractionConfidence.EXACT_MATCH,
            analytical_confidence=analytical_confidence,
            cell=None,
            derived_from=derived_from,
        )

    @property
    def source_refs(self) -> tuple[str, ...]:
        """Row IDs for a mapped value; input concept names for a derived one."""
        if self.cell is not None:
            return (self.cell.ref.ref_id,)
        return self.derived_from or ()

    @property
    def source_page(self) -> int | None:
        return self.cell.ref.page if self.cell is not None else None

    @property
    def source_label(self) -> str | None:
        return self.cell.ref.row_label if self.cell is not None else None

    @property
    def source_text(self) -> str | None:
        return self.cell.raw_token if self.cell is not None else None


@dataclass(frozen=True, slots=True)
class RowMapping:
    """A claim that one document row carries one concept. Numbers come later."""

    concept: CanonicalConcept
    ref_id: str
    kind: StatementKind
    extraction_confidence: ExtractionConfidence


@dataclass(frozen=True, slots=True)
class MappingReport:
    """Validated values plus an explicit reason for every value that is absent."""

    values: tuple[FinancialValue, ...]
    unavailable: Mapping[tuple[CanonicalConcept, Period], Unavailable]
    unmapped: tuple[CanonicalConcept, ...]
    conflicts: tuple[Unavailable, ...]

    def get(self, concept: CanonicalConcept, period: Period) -> Maybe[FinancialValue]:
        for v in self.values:
            if v.concept is concept and v.period == period:
                return v
        found = self.unavailable.get((concept, period))
        if found is not None:
            return found
        return Unavailable(
            UnavailableReason.MISSING_INPUT, f"{concept.value} not mapped for {period.end_year}"
        )


class MetricUnit(Enum):
    RATIO = "ratio"
    PERCENT = "percent"
    CURRENCY = "currency"


@dataclass(frozen=True, slots=True)
class Metric:
    """A calculated figure and the provenance of everything that fed it."""

    name: str
    period: Period
    value: Decimal
    unit: MetricUnit
    inputs: tuple[str, ...]  # ref_ids and/or concept names
    analytical_confidence: AnalyticalConfidence


@dataclass(frozen=True, slots=True)
class MetricSet:
    """Mapped plus derived values, every metric, and a reason for every absent one."""

    values: tuple[FinancialValue, ...]
    metrics: tuple[Metric, ...]
    unavailable: Mapping[tuple[str, Period], Unavailable]

    def value(self, concept: CanonicalConcept, period: Period) -> Maybe[FinancialValue]:
        for v in self.values:
            if v.concept is concept and v.period == period:
                return v
        found = self.unavailable.get((concept.value, period))
        if found is not None:
            return found
        return Unavailable(
            UnavailableReason.MISSING_INPUT, f"{concept.value} unavailable for {period.end_year}"
        )

    def metric(self, name: str, period: Period) -> Maybe[Metric]:
        for m in self.metrics:
            if m.name == name and m.period == period:
                return m
        found = self.unavailable.get((name, period))
        if found is not None:
            return found
        return Unavailable(
            UnavailableReason.MISSING_INPUT, f"{name} not computed for {period.end_year}"
        )


class Direction(Enum):
    UP = "up"
    DOWN = "down"
    FLAT = "flat"


class EconomicSense(Enum):
    """Whether the movement is good or bad for the business. Assigned in Python."""

    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"


@dataclass(frozen=True, slots=True)
class Trend:
    """A change between two adjacent periods. Never more than two."""

    subject: str  # concept or metric name
    from_period: Period
    to_period: Period
    absolute_change: Decimal
    relative_change: Maybe[Decimal]
    direction: Direction
    economic: EconomicSense


@dataclass(frozen=True, slots=True)
class TrendSet:
    trends: tuple[Trend, ...]
    unavailable: Mapping[tuple[str, Period], Unavailable]  # (subject, to_period)

    def get(self, subject: str, to_period: Period) -> Maybe[Trend]:
        for t in self.trends:
            if t.subject == subject and t.to_period == to_period:
                return t
        found = self.unavailable.get((subject, to_period))
        if found is not None:
            return found
        return Unavailable(
            UnavailableReason.MISSING_INPUT, f"no {subject} change into {to_period.end_year}"
        )


class ReconciliationStatus(Enum):
    """Soft by design. There is deliberately no hard-failure state."""

    PASSED = "passed"
    WARNING = "warning"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class ReconciliationCheck:
    name: str
    period: Period
    status: ReconciliationStatus
    left: Maybe[Decimal]
    right: Maybe[Decimal]
    delta: Maybe[Decimal]
    tolerance: Decimal
    detail: str
    refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReconciliationReport:
    checks: tuple[ReconciliationCheck, ...]

    def get(self, name: str, period: Period) -> ReconciliationCheck | None:
        for c in self.checks:
            if c.name == name and c.period == period:
                return c
        return None

    @property
    def warnings(self) -> tuple[ReconciliationCheck, ...]:
        return tuple(c for c in self.checks if c.status is ReconciliationStatus.WARNING)


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RuleOutcome(Enum):
    """'Checked and clean' and 'could not check' are different answers."""

    FIRED = "fired"
    CLEAR = "clear"
    NOT_EVALUATED = "not_evaluated"


@dataclass(frozen=True, slots=True)
class RedFlag:
    rule_id: str
    outcome: RuleOutcome
    severity: Severity
    message: str
    refs: tuple[str, ...]
    reason: Unavailable | None = None  # set when outcome is NOT_EVALUATED


@dataclass(frozen=True, slots=True)
class AnalysisResult:
    """What the pipeline returns. Assembled in Phase 8."""

    document_id: str
    statements: StatementSet
    periods: Maybe[PeriodMap]  # Unavailable(AMBIGUOUS) for the whole document is a valid result
    values: tuple[FinancialValue, ...]  # mapped and derived
    metrics: tuple[Metric, ...]
    trends: tuple[Trend, ...]
    reconciliations: tuple[ReconciliationCheck, ...]
    red_flags: tuple[RedFlag, ...]
    mapping: MappingReport
    metric_set: MetricSet
    trend_set: TrendSet
    reconciliation_report: ReconciliationReport

    @property
    def basis(self) -> StatementBasis:
        """Surfaced at the top level so a standalone fallback is never quiet."""
        return self.statements.basis


# ---------------------------------------------------------------------------
# Phase 9: grounded narrative. Extends the provenance chain past RedFlag.
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Insight:
    """One narrative point. `cites` are evidence IDs the validator confirmed exist
    (metric@year, rule ids, reconciliation@year, concept@year). Every number in
    `text` was checked against the numbers the model was shown."""

    text: str
    cites: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Narrative:
    summary: str
    insights: tuple[Insight, ...]
    model: str  # which model produced it, for the UI label
