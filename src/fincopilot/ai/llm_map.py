"""Phase 5 row picker. Spec 6.3.

The model receives a concept definition and candidate row labels with IDs.
It NEVER receives a financial number. It returns a row ID or null. Every
response passes a six-path validation gate that rejects and never repairs.
Python then pulls the number from the validated row, exactly as it does for
a deterministic match.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from fincopilot.ai.client import LLMClient
from fincopilot.mapping.synonyms import CONCEPT_STATEMENT
from fincopilot.types import (
    CanonicalConcept,
    ExtractionConfidence,
    NormalizedTable,
    NormalizedTables,
    RowMapping,
    SourceRef,
    Unavailable,
    UnavailableReason,
)

log = logging.getLogger(__name__)

MAX_CANDIDATES = 40
MAX_RESPONSE_BYTES = 64 * 1024  # a row ID and a sentence; anything bigger is not an answer

RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source_row_id": {"type": ["string", "null"]},
        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
        "reasoning": {"type": "string"},
    },
    "required": ["source_row_id"],
    "additionalProperties": False,
}

# Derived concepts are computed by calc/ from their inputs (spec 7.2). Reports
# do not print them as statement lines, and a small model asked to find one
# picks a neighbour instead: Wipro's "net cash from investing activities" came
# back as free cash flow. The exact-match tables may still map a printed row.
NEVER_ASK = frozenset(
    {CanonicalConcept.EBITDA, CanonicalConcept.FREE_CASH_FLOW, CanonicalConcept.TOTAL_DEBT}
)

DEFINITIONS: dict[CanonicalConcept, str] = {
    CanonicalConcept.REVENUE: "Revenue from the core business (net sales). NOT total income, "
    "which includes other income.",
    CanonicalConcept.GROSS_PROFIT: "Revenue minus cost of goods sold.",
    CanonicalConcept.COGS: "Cost of goods sold or cost of materials consumed / cost of sales.",
    CanonicalConcept.OPERATING_INCOME: "Profit from operations before finance costs and tax.",
    CanonicalConcept.D_AND_A: "Depreciation and amortisation expense for the period.",
    CanonicalConcept.EBITDA: "Earnings before interest, tax, depreciation and amortisation.",
    CanonicalConcept.NET_INCOME: "Profit for the year after tax.",
    CanonicalConcept.TOTAL_ASSETS: "Total assets on the balance sheet.",
    CanonicalConcept.CURRENT_ASSETS: "Total current assets.",
    CanonicalConcept.CASH: "Cash and cash equivalents on the balance sheet.",
    CanonicalConcept.TOTAL_LIABILITIES: "Total liabilities, NOT total current liabilities and "
    "NOT total equity and liabilities.",
    CanonicalConcept.CURRENT_LIABILITIES: "Total current liabilities.",
    CanonicalConcept.SHORT_TERM_BORROWINGS: "Short-term or current borrowings / debt.",
    CanonicalConcept.LONG_TERM_BORROWINGS: "Long-term or non-current borrowings / debt.",
    CanonicalConcept.TOTAL_DEBT: "Total borrowings, short and long term combined.",
    CanonicalConcept.EQUITY: "Total equity attributable to shareholders.",
    CanonicalConcept.OPERATING_CASH_FLOW: "Net cash from operating activities.",
    CanonicalConcept.CAPEX: "Cash paid to purchase property, plant and equipment.",
    CanonicalConcept.FREE_CASH_FLOW: "Operating cash flow minus capital expenditure.",
}


def candidate_rows(table: NormalizedTable, claimed: set[str]) -> list[tuple[str, str]]:
    """(ref_id, label) for unmapped rows that carry at least one value. Capped."""
    with_values = {ref_id for (ref_id, _) in table.cells}
    out = [
        (r.ref.ref_id, r.label)
        for r in table.table.rows
        if r.ref.ref_id in with_values and r.ref.ref_id not in claimed
    ]
    return out[:MAX_CANDIDATES]


def build_prompt(concept: CanonicalConcept, candidates: Sequence[tuple[str, str]]) -> str:
    lines = [
        "You are matching one financial statement line item to a concept.",
        f"Concept: {concept.value}",
        f"Definition: {DEFINITIONS[concept]}",
        "Candidate rows (id: label). Pick the ONE row whose label means exactly this",
        "concept, or answer null if none does. Do not guess.",
    ]
    lines += [f"- {ref_id}: {label}" for ref_id, label in candidates]
    lines.append(
        'Answer as JSON: {"source_row_id": "<id or null>", "confidence": "high|medium|low"}'
    )
    return "\n".join(lines)


def _has_numeric(value: Any) -> bool:
    """Iterative on purpose: model output picks the nesting depth, not us."""
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, bool):
            continue
        if isinstance(item, int | float):
            return True
        if isinstance(item, dict):
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)
    return False


def _no_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """A response that declines AND picks is malformed, not last-wins."""
    out: dict[str, Any] = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"duplicate key {key!r}")
        out[key] = value
    return out


def validate_response(
    raw: str,
    *,
    concept: CanonicalConcept,
    candidate_ids: set[str],
    refs: Mapping[str, SourceRef],
    already_mapped: Mapping[str, CanonicalConcept],
) -> RowMapping | Unavailable | None:
    """Six rejection paths from spec 6.3. None means the model declined.

    Parsing is fenced with a size cap and a catch-all: deep nesting raises
    RecursionError, which is not a ValueError, and an untrusted model must
    never be able to raise anything out of this function.
    """
    if not isinstance(raw, str | bytes) or len(raw) > MAX_RESPONSE_BYTES:
        return Unavailable(UnavailableReason.UNPARSEABLE, "LLM response is absent or oversized")
    try:
        data = json.loads(raw, object_pairs_hook=_no_duplicate_keys)
        numeric = _has_numeric(data)
        shape_ok = (
            isinstance(data, dict)
            and "source_row_id" in data
            and set(data) <= {"source_row_id", "confidence", "reasoning"}
            and (data["source_row_id"] is None or isinstance(data["source_row_id"], str))
            and ("confidence" not in data or data["confidence"] in ("high", "medium", "low"))
            and ("reasoning" not in data or isinstance(data["reasoning"], str))
        )
    except Exception:  # ValueError, TypeError, RecursionError, UnicodeDecodeError, ...
        return Unavailable(UnavailableReason.UNPARSEABLE, "LLM response is not valid JSON")

    if numeric:  # path 6, checked first so it is logged even when shape is fine
        log.warning("LLM contract violation: numeric field in response for %s", concept.value)
        return Unavailable(UnavailableReason.CONFLICT, "LLM response contains a numeric field")
    if not shape_ok:
        return Unavailable(UnavailableReason.UNPARSEABLE, "LLM response violates the schema")

    row_id = data["source_row_id"]
    if row_id is None:
        return None
    if row_id not in refs:
        return Unavailable(
            UnavailableReason.CONFLICT, f"LLM returned unknown ref {row_id!r}", refs=(row_id,)
        )
    if row_id not in candidate_ids:
        return Unavailable(
            UnavailableReason.CONFLICT,
            f"LLM returned {row_id!r}, which is outside the {concept.value} statement scope",
            refs=(row_id,),
        )
    if row_id in already_mapped:
        return Unavailable(
            UnavailableReason.CONFLICT,
            f"{row_id} is already mapped to {already_mapped[row_id].value}",
            refs=(row_id,),
        )
    return RowMapping(concept, row_id, CONCEPT_STATEMENT[concept], ExtractionConfidence.LLM_MAPPED)


def fill_unmapped(
    mappings: tuple[RowMapping, ...],
    normalized: NormalizedTables,
    refs: Mapping[str, SourceRef],
    client: LLMClient,
) -> tuple[RowMapping, ...]:
    """Ask the model only for concepts still unmapped after Tier 2. Failure = unmapped."""
    tables = {
        t.kind: t
        for t in (normalized.income, normalized.balance, normalized.cash_flow)
        if isinstance(t, NormalizedTable)
    }
    already: dict[str, CanonicalConcept] = {m.ref_id: m.concept for m in mappings}
    mapped_concepts = {m.concept for m in mappings}
    added: list[RowMapping] = []
    for concept in CanonicalConcept:
        if concept in mapped_concepts or concept in NEVER_ASK:
            continue
        table = tables.get(CONCEPT_STATEMENT[concept])
        if table is None:
            continue
        candidates = candidate_rows(table, set(already))
        if not candidates:
            continue
        try:
            raw = client.complete_json(build_prompt(concept, candidates), RESPONSE_SCHEMA)
            result = validate_response(
                raw,
                concept=concept,
                candidate_ids={c[0] for c in candidates},
                refs=refs,
                already_mapped=already,
            )
        except Exception as exc:  # unreachable, timeout, garbage: the concept stays unmapped
            log.info("LLM fallback unavailable for %s: %s", concept.value, type(exc).__name__)
            continue
        if isinstance(result, RowMapping):
            added.append(result)
            already[result.ref_id] = concept
            mapped_concepts.add(concept)
    return mappings + tuple(added)
