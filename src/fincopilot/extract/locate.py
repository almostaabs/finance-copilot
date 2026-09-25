"""Statement location: anchors, scoped scoring, and multi-page stitching.

Pure function of RawDocument. Spec section 4.3 and 4.4. This is the most
failure-prone step in the system, which is why it is its own module with its
own scoring and its own tests.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass

from fincopilot.extract.anchors import (
    Scope,
    anchor_lines,
    find_anchors,
    is_amount_token,
    is_numeric_dense,
    is_sec_annual_report,
)
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

_YEAR = re.compile(r"(?<![0-9])(?:19|20|21)[0-9]{2}(?![0-9])")
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
    # The label column's left edge moves with indentation ("Cash" under a
    # segment heading starts further right); the value columns do not.
    ax, bx = a.col_x[1:] or a.col_x, b.col_x[1:] or b.col_x
    return all(abs(x - y) <= _COL_X_TOLERANCE for x, y in zip(ax, bx, strict=True))


def _is_continuation(prev: ExtractedTable, cur: ExtractedTable) -> bool:
    return (
        cur.first_page == prev.pages[-1] + 1
        and _column_count(prev) == _column_count(cur) > 0
        and (cur.header == () or cur.header == prev.header)
        and prev.header != ()
        and _positions_match(prev, cur)
    )


def _same_heading(page_texts: tuple[str, ...] | None, prev_page: int, cur_page: int) -> bool:
    """A continuation page repeats the statement's own heading or has none.
    Any other heading means a new statement starts there (Apple's cash flow
    follows its equity statement with identical geometry)."""
    if page_texts is None:
        return True
    cur = anchor_lines(page_texts[cur_page - 1])
    return cur == () or cur == anchor_lines(page_texts[prev_page - 1])


def stitch_tables(
    tables: tuple[ExtractedTable, ...], page_texts: tuple[str, ...] | None = None
) -> tuple[ExtractedTable, ...]:
    """Merge page-split tables. Every row keeps its TRUE page in its SourceRef.

    A continuation may sit behind an unrelated table on the same page (real
    reports often carry a small ruled table beside the statement), so the
    search runs over every table already kept that ends on the previous page,
    taking the first match in page-then-id order."""
    ordered = sorted(tables, key=lambda t: (t.first_page, t.table_id))
    out: list[ExtractedTable] = []
    for cur in ordered:
        idx = next(
            (
                i
                for i, prev in enumerate(out)
                if _is_continuation(prev, cur)
                and _same_heading(page_texts, prev.pages[-1], cur.first_page)
            ),
            None,
        )
        if idx is None:
            out.append(cur)
            continue
        prev = out[idx]
        out[idx] = ExtractedTable(
            table_id=prev.table_id,
            first_page=prev.first_page,
            pages=prev.pages + cur.pages,
            header=prev.header,
            rows=prev.rows + cur.rows,
            caption=prev.caption,
            col_x=prev.col_x,
        )
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


def _header_years(t: ExtractedTable) -> list[str]:
    return [m.group(0) for c in t.header for m in [_YEAR.search(c)] if m]


def score_table(kind: StatementKind, t: ExtractedTable) -> int:
    """Keyword rows dominate; a period-bearing header helps; a header that names
    the same year twice (convenience-translation columns) can never yield a
    period map, so it is pushed below any clean alternative."""
    years = _header_years(t)
    bonus = 5 * min(len(years), 3)
    if len(years) != len(set(years)):
        bonus -= 20
    return 10 * _keyword_hits(kind, t) + _numeric_columns(t) + min(len(t.rows), 30) + bonus


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


CLUSTER_GAP_PAGES = 15  # anchored pages closer than this belong to one set of statements


def _clusters(cands: list[_Candidate]) -> list[list[_Candidate]]:
    groups: list[list[_Candidate]] = []
    for c in sorted(cands, key=lambda c: (c.table.first_page, c.table.table_id)):
        if groups and c.table.first_page - groups[-1][-1].table.first_page <= CLUSTER_GAP_PAGES:
            groups[-1].append(c)
        else:
            groups.append([c])
    return groups


def _choose(cands: list[_Candidate], scopes: set[Scope]) -> dict[StatementKind, _Candidate]:
    """One coherent set of statements, not the best page of each.

    Reports that print their statements twice (Ind AS and IFRS, group and
    parent) would otherwise mix sets. Candidates are grouped by page
    neighbourhood; each group offers its best table per kind; the group with
    the highest total wins, with a bonus per statement it can supply. Ties go
    to the earlier group."""
    best: dict[StatementKind, _Candidate] = {}
    best_total = None
    for group in _clusters([c for c in cands if c.scope in scopes]):
        picks: dict[StatementKind, _Candidate] = {}
        for kind in StatementKind:
            pool = [c for c in group if c.kind is kind]
            if pool:
                picks[kind] = max(pool, key=lambda c: (c.score, -c.table.first_page))
        total = sum(c.score for c in picks.values()) + COMPLETENESS_BONUS * len(picks)
        if best_total is None or total > best_total:
            best, best_total = picks, total
    return best


COMPLETENESS_BONUS = 25


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
    """Consolidated wins whenever it exists (explicitly, or unprefixed under a 10-K
    cover page). Standalone is a labelled fallback."""
    tables = stitch_tables(doc.tables, doc.page_text)
    cands = _anchor_candidates(doc, tables)

    if any(c.scope is Scope.CONSOLIDATED for c in cands):
        basis, scopes = StatementBasis.CONSOLIDATED, {Scope.CONSOLIDATED}
    elif any(c.scope is Scope.UNPREFIXED for c in cands) and any(
        is_sec_annual_report(t) for t in doc.page_text
    ):
        # A 10-K's primary statements are consolidated whatever their titles
        # say (Microsoft: "INCOME STATEMENTS"). Evidence, not assumption: a
        # cover page must be present. An explicit "Standalone" is never promoted.
        basis, scopes = StatementBasis.CONSOLIDATED, {Scope.UNPREFIXED}
    elif any(c.scope in (Scope.STANDALONE, Scope.UNPREFIXED) for c in cands):
        basis, scopes = StatementBasis.STANDALONE_FALLBACK, {Scope.STANDALONE, Scope.UNPREFIXED}
    else:
        basis, scopes = StatementBasis.UNKNOWN, set()

    chosen = _choose(cands, scopes)

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
