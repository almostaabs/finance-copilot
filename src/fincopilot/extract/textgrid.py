"""Whitespace-aligned statements: columns recovered from word positions.

Most real annual reports print their primary statements without ruling
lines, so pdfplumber's lattice finder returns one-column rows. This module
rebuilds the grid from word coordinates:

- amount tokens are right-aligned, so their right edges cluster into columns
- the header is the line above the first data row whose year tokens map one
  to one onto those columns
- a column whose header carries no year and whose values are all small
  plain integers is a notes column, and is dropped
- a sub-header line under the years ("Amount  % Sales") is header, not body;
  when it prints a % sub-column, only the sub-column printed as "Amount" takes
  the year, and without one the years are withheld
- a year-only header line below data rows starts a new table, so a footnote
  table printed under a statement never becomes part of it

Everything is geometric and deterministic. No text is altered; every cell is
the exact token printed on the page.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

_YEAR = re.compile(r"^(?:19|20|21)[0-9]{2}$")
_NUMBER = r"-?[0-9](?:[0-9,]*[0-9])?(?:\.[0-9]+)?"
# A closing paren needs its opening one: "(Note 9)" wraps onto the label as
# "(Note" + "9)", and "9)" read as an amount cuts the label in half.
_AMOUNT = re.compile(rf"^(?:\({_NUMBER}\)?|{_NUMBER})%?$")
_SKIP = frozenset({"$", "Rs.", "Rs", "\u20b9", "USD", "INR"})
_DASH = frozenset({"-", "\u2013", "\u2014", "Nil", "NIL", "nil"})
_NOTE = re.compile(r"^[0-9]{1,3}(?:\([a-z]\))?$")
_AMOUNT_HEADER = re.compile(r"\bamounts?\b", re.I)

LINE_TOL = 3.0  # points; words within this vertical distance share a line
COL_GAP = 14.0  # points; right edges further apart than this start a new column
COL_SLACK = 6.0  # points; a token may overhang a column's span by this much
MIN_COLUMNS = 2
MIN_DATA_ROWS = 3


@dataclass(frozen=True, slots=True)
class Word:
    text: str
    x0: float
    x1: float
    top: float


def _lines(words: list[Word]) -> list[list[Word]]:
    out: list[list[Word]] = []
    finite = [w for w in words if all(map(math.isfinite, (w.x0, w.x1, w.top))) and w.text]
    for w in sorted(finite, key=lambda w: (round(w.top), w.x0)):
        if out and abs(out[-1][0].top - w.top) <= LINE_TOL:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(line, key=lambda w: w.x0) for line in out]


def _is_value(text: str) -> bool:
    return bool(_AMOUNT.match(text)) or text in _DASH


def _join_parens(line: list[Word]) -> list[Word]:
    """Some typesetters put a closing paren in its own column: '(21,998' + ')'."""
    out: list[Word] = []
    for w in line:
        if (
            w.text == ")"
            and out
            and out[-1].text.startswith("(")
            and not out[-1].text.endswith(")")
        ):
            prev = out.pop()
            out.append(Word(prev.text + ")", prev.x0, w.x1, prev.top))
        else:
            out.append(w)
    return out


def _split(line: list[Word]) -> tuple[list[Word], list[Word]]:
    """Label words, then the trailing run of value tokens (currency signs dropped)."""
    line = _join_parens(line)
    i = len(line)
    while i > 0 and (_is_value(line[i - 1].text) or line[i - 1].text in _SKIP):
        i -= 1
    label = line[:i]
    values = [w for w in line[i:] if w.text not in _SKIP]
    return label, values


def _clusters(edges: list[float]) -> list[tuple[float, float]]:
    """Group sorted right edges; each cluster becomes (min_edge, max_edge)."""
    out: list[list[float]] = []
    for e in sorted(edges):
        if out and e - out[-1][-1] <= COL_GAP:
            out[-1].append(e)
        else:
            out.append([e])
    return [(c[0], c[-1]) for c in out if len(c) >= 2]


def _column_of(w: Word, spans: list[tuple[float, float]]) -> int | None:
    for i, (lo, hi) in enumerate(spans):
        if lo - COL_SLACK <= w.x1 <= hi + COL_SLACK:
            return i
    return None


def _nearest(center: float, spans: list[tuple[float, float]]) -> int:
    return min(range(len(spans)), key=lambda i: abs((spans[i][0] + spans[i][1]) / 2 - center))


def _extents(data: list, spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Each column's printed width: leftmost start to rightmost end of its values."""
    ext = [(math.inf, -math.inf)] * len(spans)
    for _, _, values in data:
        for v in values:
            c = _column_of(v, spans)
            if c is not None:
                ext[c] = (min(ext[c][0], v.x0), max(ext[c][1], v.x1))
    return ext


def _over(w: Word, extents: list[tuple[float, float]]) -> int | None:
    """The column a header word overlaps most, if any."""
    best, col = 0.0, None
    for c, (lo, hi) in enumerate(extents):
        overlap = min(w.x1, hi + COL_SLACK) - max(w.x0, lo - COL_SLACK)
        if overlap > best:
            best, col = overlap, c
    return col


def _sub_headers(
    lines: list[list[Word]], extents: list[tuple[float, float]]
) -> tuple[set[int], list[str]]:
    """Header lines under the year line ("Amount  % Sales"): their indices in
    `lines`, and the text each prints over each column. Such a line has no
    value token and words over at least two columns."""
    found: set[int] = set()
    text = [""] * len(extents)
    for i, line in enumerate(lines):
        if any(_is_value(w.text) for w in line):
            continue
        cols = [(_over(w, extents), w) for w in line]
        if len({c for c, _ in cols if c is not None}) < MIN_COLUMNS:
            continue
        found.add(i)
        for c, w in cols:
            if c is not None:
                text[c] = (text[c] + " " + w.text).strip()
    return found, text


def _amount_header(
    years: list[Word], extents: list[tuple[float, float]], sub: list[str]
) -> list[str]:
    """Year per column when a year spans an amount and a % sub-column.

    Each sub-column belongs to its nearest year; within that year the printed
    sub-header, never position, names the amount column. If it does not name
    exactly one, no column gets a year and the statement's periods are withheld.
    """
    header = [""] * len(extents)
    printed = [c for c, (lo, hi) in enumerate(extents) if lo <= hi]
    owner = {
        c: min(years, key=lambda y: abs((y.x0 + y.x1) / 2 - sum(extents[c]) / 2)) for c in printed
    }
    for y in years:
        amount = [c for c in printed if owner[c] is y and _AMOUNT_HEADER.search(sub[c])]
        if len(amount) != 1:
            return [""] * len(extents)
        header[amount[0]] = y.text
    return header


def _is_year_header(line: list[Word]) -> bool:
    values = _split(line)[1]
    return len(values) >= MIN_COLUMNS and all(_YEAR.match(v.text) for v in values)


def text_grids(words: list[Word]) -> list[tuple[list[list[str]], tuple[float, ...]]]:
    """One grid per table on the page.

    A page can print a second table under the statement (a footnote's VIE
    table, say) with its own year header. A year header below the first data
    row starts a new table there; otherwise the second table's rows join the
    statement and its "Total assets" competes with the statement's own.
    """
    lines = _lines(words)
    starts = [0]
    seen_data = False
    for i, line in enumerate(lines):
        if _is_year_header(line):
            if seen_data:
                starts.append(i)
                seen_data = False
        elif len(_split(line)[1]) >= MIN_COLUMNS:
            seen_data = True
    bounds = zip(starts, [*starts[1:], len(lines)], strict=True)
    grids = [_grid(lines[a:b]) for a, b in bounds]
    return [g for g in grids if g is not None]


def _grid(lines: list[list[Word]]) -> tuple[list[list[str]], tuple[float, ...]] | None:
    """One table from its lines: rows (header first) and column left edges, or None."""
    parsed = [(_split(line), line) for line in lines]
    data = [
        (i, label, values)
        for i, ((label, values), _) in enumerate(parsed)
        if label and len(values) >= 1 and not all(_YEAR.match(v.text) for v in values)
    ]
    if len(data) < MIN_DATA_ROWS:
        return None
    spans = _clusters([v.x1 for _, _, values in data for v in values])
    if len(spans) < MIN_COLUMNS:
        return None

    first_data = next((i for i, _, values in data if len(values) >= MIN_COLUMNS), data[0][0])
    header = [""] * len(spans)
    header_line = None
    for i in range(first_data - 1, -1, -1):
        years = [w for w in lines[i] if _YEAR.match(w.text)]
        if len(years) >= MIN_COLUMNS:
            for y in years:
                col = _nearest((y.x0 + y.x1) / 2, spans)
                header[col] = (header[col] + " " + y.text).strip()
            header_line = i
            break
    if header_line is None:
        return None
    extents = _extents(data, spans)
    sub_lines, sub = _sub_headers(lines[header_line + 1 : first_data], extents)
    if any("%" in text for text in sub):
        header = _amount_header(years, extents, sub)

    last_data = data[-1][0]
    body: list[list[str]] = []
    for i in range(header_line + 1, last_data + 1):
        (label, values), _ = parsed[i]
        if not label or i - header_line - 1 in sub_lines:
            continue
        cells = [""] * len(spans)
        for v in values:
            col = _column_of(v, spans)
            if col is not None and not cells[col]:
                cells[col] = v.text
        body.append([" ".join(w.text for w in label), *cells])

    keep = [
        c
        for c in range(len(spans))
        if header[c] or not all(_NOTE.match(r[c + 1]) for r in body if r[c + 1])
    ]
    if sum(1 for c in keep if header[c]) >= MIN_COLUMNS:
        # A numeric column with no year over it cannot be given a period; it is
        # usually a convenience translation or a note. Leave it out rather than
        # let one unlabelled column make every period in the document ambiguous.
        keep = [c for c in keep if header[c]]
    if len(keep) < MIN_COLUMNS:
        return None
    rows = [["", *(header[c] for c in keep)]] + [[r[0], *(r[c + 1] for c in keep)] for r in body]
    label_x0 = min(w.x0 for _, label, _ in data for w in label)
    col_x = (round(label_x0, 1), *(round(spans[c][0], 1) for c in keep))
    return rows, col_x
