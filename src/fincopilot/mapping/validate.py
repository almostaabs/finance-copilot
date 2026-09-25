"""Claim validation. Spec 2.5, 6.4.

Validates claims, not existence: every ref_id is looked up in the extracted
document, one value per concept x period is enforced, and PYTHON pulls each
number from the normalised cell. Nothing here accepts a number from a caller.
"""

from __future__ import annotations

from collections import defaultdict

from fincopilot.mapping.synonyms import CONCEPT_STATEMENT, normalize_label
from fincopilot.types import (
    AnalyticalConfidence,
    CanonicalConcept,
    FinancialValue,
    MappingNote,
    MappingReport,
    NormalizedTable,
    NormalizedTables,
    Period,
    PeriodMap,
    RowMapping,
    StatementKind,
    Unavailable,
    UnavailableReason,
)


def _tables(normalized: NormalizedTables) -> dict[StatementKind, NormalizedTable]:
    out = {}
    for t in (normalized.income, normalized.balance, normalized.cash_flow):
        if isinstance(t, NormalizedTable):
            out[t.kind] = t
    return out


def _is_total(table: NormalizedTable, ref_id: str) -> bool:
    """A row printed as a total. A bare "Total" can only have been claimed
    through its section heading (map_rows), so it counts as one too."""
    label = next(normalize_label(r.label) for r in table.table.rows if r.ref.ref_id == ref_id)
    return label == "total" or label.startswith("total ")


def _total_of(claims: list[RowMapping], table: NormalizedTable) -> RowMapping | None:
    """Of two rows claiming one concept, the one total row; None if undecidable.

    A statement prints components and then their total ("Net sales", ...,
    "Total"); the component must never win over the total."""
    if len(claims) != 2:
        return None
    totals = [c for c in claims if _is_total(table, c.ref_id)]
    return totals[0] if len(totals) == 1 else None


def validate_mappings(
    mappings: tuple[RowMapping, ...],
    normalized: NormalizedTables,
    periods: PeriodMap,
) -> MappingReport:
    """Reject duplicates and wrong-statement claims; build values from cells."""
    tables = _tables(normalized)
    conflicts: list[Unavailable] = []
    by_concept: dict[CanonicalConcept, list[RowMapping]] = defaultdict(list)
    for m in mappings:
        if CONCEPT_STATEMENT[m.concept] is not m.kind:
            conflicts.append(
                Unavailable(
                    UnavailableReason.CONFLICT,
                    f"{m.concept.value} claimed from the {m.kind.value} statement",
                    refs=(m.ref_id,),
                )
            )
            continue
        table = tables.get(m.kind)
        if table is None or m.ref_id not in {r.ref.ref_id for r in table.table.rows}:
            conflicts.append(
                Unavailable(
                    UnavailableReason.CONFLICT,
                    f"{m.concept.value}: ref {m.ref_id} is not a row of the located statement",
                    refs=(m.ref_id,),
                )
            )
            continue
        by_concept[m.concept].append(m)

    values: list[FinancialValue] = []
    unavailable: dict[tuple[CanonicalConcept, Period], Unavailable] = {}
    accepted: dict[CanonicalConcept, RowMapping] = {}
    notes: list[MappingNote] = []
    for concept, claims in by_concept.items():
        if len({c.ref_id for c in claims}) > 1:
            table = tables[CONCEPT_STATEMENT[concept]]
            total = _total_of(claims, table)
            if total is not None:
                accepted[concept] = total
                dropped = next(c for c in claims if c.ref_id != total.ref_id)
                notes.append(
                    MappingNote(
                        concept=concept,
                        kind=total.kind,
                        kept_ref=total.ref_id,
                        dropped_ref=dropped.ref_id,
                        dropped_label=next(
                            r.label for r in table.table.rows if r.ref.ref_id == dropped.ref_id
                        ),
                        reason="total row preferred over component",
                    )
                )
                continue
            conflict = Unavailable(
                UnavailableReason.CONFLICT,
                f"{concept.value}: {len(claims)} rows claim it",
                refs=tuple(c.ref_id for c in claims),
            )
            conflicts.append(conflict)
            for period in periods.periods_for(CONCEPT_STATEMENT[concept]):
                unavailable[(concept, period)] = conflict
            continue
        accepted[concept] = claims[0]

    for concept, claim in accepted.items():
        table = tables[claim.kind]
        for (kind, col), period in periods.columns.items():
            if kind is not claim.kind:
                continue
            cell = table.cells.get((claim.ref_id, col))
            if cell is None:
                unavailable[(concept, period)] = Unavailable(
                    UnavailableReason.MISSING_INPUT,
                    f"{concept.value} {period.end_year}: column holds no value",
                    refs=(claim.ref_id,),
                )
            elif isinstance(cell, Unavailable):
                unavailable[(concept, period)] = Unavailable(
                    cell.reason,
                    f"{concept.value} {period.end_year}: {cell.detail}",
                    refs=cell.refs,
                    cause=cell,
                )
            else:
                values.append(
                    FinancialValue.from_cell(
                        concept=concept,
                        period=period,
                        cell=cell,
                        extraction_confidence=claim.extraction_confidence,
                        analytical_confidence=AnalyticalConfidence.HIGH,
                    )
                )

    unmapped = tuple(c for c in CanonicalConcept if c not in accepted)
    return MappingReport(
        values=tuple(values),
        unavailable=unavailable,
        unmapped=unmapped,
        conflicts=tuple(conflicts),
        notes=tuple(notes),
    )
