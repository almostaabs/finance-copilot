"""Statement location: anchors, scoped scoring, and multi-page stitching.

Pure function of RawDocument. Spec section 4.3 and 4.4. This is the most
failure-prone step in the system, which is why it is its own module with its
own scoring and its own tests.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from fincopilot.extract.anchors import Scope, find_anchors, is_amount_token, is_numeric_dense
from fincopilot.types import (
    ExtractedTable,
    RawDocument,
    Statement,
    StatementBasis,
    StatementKind,
    StatementSet,
    Unavailable,
    UnavailableReason,
)

# Row-label keywords used ONLY to score candidate tables. Not the mapping
# vocabulary: extract may not import mapping.
_KEYWORDS: dict[StatementKind, tuple[str, ...]] = {
    StatementKind.INCOME: ("revenue", "sales", "profit", "income", "expense", "tax", "cost"),
    StatementKind.BALANCE: (
        "assets",
        "liabilities",
        "equity",
        "borrowings",
        "payables",
        "receivables",
        "inventor",
        "debt",
    ),
    StatementKind.CASH_FLOW: (
        "operating activities",
        "investing activities",
        "financing activities",
        "cash flow",
        "net cash",
    ),
}

MIN_FALLBACK_SCORE = 13  # at least one keyword row, one numeric column, two rows
_COL_X_TOLERANCE = 5.0  # PDF points


@dataclass(frozen=True, slots=True)
class _Candidate:
    kind: StatementKind
    scope: Scope | None  # None: found by the scored fallback, scope unknown
    table: ExtractedTable
    score: int


def _column_count(t: ExtractedTable) -> int:
    if t.header:
        return len(t.header)
    return len(t.rows[0].cells) if t.rows else 0


def _positions_match(a: ExtractedTable, b: ExtractedTable) -> bool:
    if not a.col_x or not b.col_x:
        return True  # no geometry recorded; column count already agreed
    if len(a.col_x) != len(b.col_x):
        return False
    return all(abs(x - y) <= _COL_X_TOLERANCE for x, y in zip(a.col_x, b.col_x, strict=True))


def _is_continuation(prev: ExtractedTable, cur: ExtractedTable) -> bool:
    return (
        cur.first_page == prev.pages[-1] + 1
        and _column_count(prev) == _column_count(cur) > 0
        and cur.header == ()
        and prev.header != ()
        and _positions_match(prev, cur)
    )


def stitch_tables(tables: tuple[ExtractedTable, ...]) -> tuple[ExtractedTable, ...]:
    """Merge page-split tables. Every row keeps its TRUE page in its SourceRef."""
    ordered = sorted(tables, key=lambda t: (t.first_page, t.table_id))
    out: list[ExtractedTable] = []
    for cur in ordered:
        if out and _is_continuation(out[-1], cur):
            prev = out.pop()
            out.append(
                ExtractedTable(
                    table_id=prev.table_id,
                    first_page=prev.first_page,
                    pages=prev.pages + cur.pages,
                    header=prev.header,
                    rows=prev.rows + cur.rows,
                    caption=prev.caption,
                    col_x=prev.col_x,
                )
            )
        else:
            out.append(cur)
    return tuple(out)


def _numeric_columns(t: ExtractedTable) -> int:
    n = _column_count(t)
    count = 0
    for col in range(1, n):
        cells = [r.cells[col] for r in t.rows if col < len(r.cells)]
        if cells and sum(1 for c in cells if is_amount_token(c)) * 2 > len(cells):
            count += 1
    return count


def _keyword_hits(kind: StatementKind, t: ExtractedTable) -> int:
    keywords = _KEYWORDS[kind]
    return sum(1 for r in t.rows if any(k in r.label.lower() for k in keywords))


def score_table(kind: StatementKind, t: ExtractedTable) -> int:
    return 10 * _keyword_hits(kind, t) + _numeric_columns(t) + min(len(t.rows), 30)


def _anchor_candidates(doc: RawDocument, tables: tuple[ExtractedTable, ...]) -> list[_Candidate]:
    by_page: dict[int, list[ExtractedTable]] = defaultdict(list)
    for t in tables:
        by_page[t.first_page].append(t)

    out: list[_Candidate] = []
    for page_no, page_tables in by_page.items():
        anchors = find_anchors(doc.page_text[page_no - 1])
        if not anchors:
            continue
        if len(anchors) == len(page_tables):
            pairs = zip(anchors, page_tables, strict=True)
        else:
            pairs = ((a, t) for a in anchors for t in page_tables)
        for (kind, scope), t in pairs:
            out.append(_Candidate(kind, scope, t, score_table(kind, t)))
    return out


def _best(cands: list[_Candidate], kind: StatementKind, scopes: set[Scope]) -> _Candidate | None:
    pool = [c for c in cands if c.kind is kind and c.scope in scopes]
    return max(pool, key=lambda c: c.score) if pool else None


def _fallback(
    doc: RawDocument,
    tables: tuple[ExtractedTable, ...],
    kind: StatementKind,
    claimed: set[str],
) -> _Candidate | None:
    """Pass 3: numeric-dense pages only, never a table already claimed or anchored."""
    pool = []
    for t in tables:
        if t.table_id in claimed:
            continue
        if find_anchors(doc.page_text[t.first_page - 1]):
            continue
        if not any(is_numeric_dense(doc.page_text[p - 1]) for p in t.pages):
            continue
        score = score_table(kind, t)
        # Row count alone must never qualify: a 500-row expense note is not a
        # cash flow statement.
        if _keyword_hits(kind, t) >= 1 and score >= MIN_FALLBACK_SCORE:
            pool.append(_Candidate(kind, None, t, score))
    return max(pool, key=lambda c: c.score) if pool else None


def locate_statements(doc: RawDocument) -> StatementSet:
    """Consolidated wins whenever it exists. Standalone is a labelled fallback."""
    tables = stitch_tables(doc.tables)
    cands = _anchor_candidates(doc, tables)

    if any(c.scope is Scope.CONSOLIDATED for c in cands):
        basis, scopes = StatementBasis.CONSOLIDATED, {Scope.CONSOLIDATED}
    elif any(c.scope in (Scope.STANDALONE, Scope.UNPREFIXED) for c in cands):
        basis, scopes = StatementBasis.STANDALONE_FALLBACK, {Scope.STANDALONE, Scope.UNPREFIXED}
    else:
        basis, scopes = StatementBasis.UNKNOWN, set()

    chosen: dict[StatementKind, _Candidate] = {}
    for kind in StatementKind:
        best = _best(cands, kind, scopes)
        if best is not None:
            chosen[kind] = best

    claimed = {c.table.table_id for c in chosen.values()}
    for kind in StatementKind:
        if kind in chosen:
            continue
        fb = _fallback(doc, tables, kind, claimed)
        if fb is not None:
            chosen[kind] = fb
            claimed.add(fb.table.table_id)

    def _result(kind: StatementKind):
        c = chosen.get(kind)
        if c is None:
            return Unavailable(
                UnavailableReason.NOT_LOCATED,
                f"no {kind.value} statement found by anchor or scored fallback",
            )
        return Statement(kind=kind, basis=basis, table=c.table)

    return StatementSet(
        basis=basis,
        income=_result(StatementKind.INCOME),
        balance=_result(StatementKind.BALANCE),
        cash_flow=_result(StatementKind.CASH_FLOW),
    )
