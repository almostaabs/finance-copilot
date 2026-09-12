"""Number grammars, dash/blank rule, scale and currency. Spec 5.2-5.5.

Every function here is pure. Numbers become Decimal in base units; nothing
here ever produces a float, NaN, or inf.
"""

from __future__ import annotations

import re
from dataclasses import replace
from decimal import Context, Decimal, Inexact
from enum import Enum

from fincopilot.types import (
    ExtractedTable,
    Maybe,
    NormalizedCell,
    Scale,
    ScaleSource,
    TableRow,
    Unavailable,
    UnavailableReason,
)

# --- number grammar ---------------------------------------------------------

# [0-9] on purpose: \d matches every Unicode decimal digit, and the grammar is
# explicit ASCII. Devanagari or Arabic-Indic numerals are UNPARSEABLE.
_WESTERN = re.compile(r"^[0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?$")
_INDIAN = re.compile(r"^[0-9]{1,2}(?:,[0-9]{2})+,[0-9]{3}(?:\.[0-9]+)?$")
_PLAIN = re.compile(r"^[0-9]+(?:\.[0-9]+)?$")

_CURRENCY_PREFIX = re.compile(r"^(?:rs\.?|inr|usd|us\$|\$|\u20b9|\u20ac|\u00a3)\s*", re.I)
_FOOTNOTE_SUFFIX = re.compile(r"[*\u2020\u2021\u00a7]+$")

DASH_TOKENS = frozenset({"-", "\u2013", "\u2014", "Nil", "NIL", "nil"})

# Scaling must be exact or refuse. The default 28-digit context would round a
# 29-digit figure silently; this one traps instead of rounding.
EXACT_CONTEXT = Context(prec=400, traps=[Inexact])


def parse_number(token: str) -> Maybe[Decimal]:
    """Explicit Western or Indian grouping grammar. Anything else is UNPARSEABLE."""
    s = token.strip()
    s = _CURRENCY_PREFIX.sub("", s)
    s = _FOOTNOTE_SUFFIX.sub("", s).strip()
    if not s:
        return Unavailable(UnavailableReason.UNPARSEABLE, f"empty token: {token!r}")

    negative = False
    if s.startswith("(") and s.endswith(")"):
        negative, s = True, s[1:-1].strip()
    elif s.endswith("-"):
        negative, s = True, s[:-1].strip()
    elif s.startswith("-"):
        negative, s = True, s[1:].strip()
    elif s.startswith("+"):
        s = s[1:].strip()

    if not (_WESTERN.match(s) or _INDIAN.match(s) or _PLAIN.match(s)):
        return Unavailable(
            UnavailableReason.UNPARSEABLE,
            f"token matches neither Western nor Indian grouping: {token!r}",
        )
    value = Decimal(s.replace(",", ""))
    return -value if negative else value


# --- dash vs blank ----------------------------------------------------------


class CellKind(Enum):
    NUMBER = "number"
    DASH_ZERO = "dash_zero"
    MISSING = "missing"
    UNPARSEABLE = "unparseable"
    TEXT = "text"


def classify_cell(token: str, *, column_is_numeric: bool) -> tuple[CellKind, Decimal | None]:
    """The decidable dash/blank rule from spec 5.4."""
    s = _CURRENCY_PREFIX.sub("", token.strip()).strip()
    if not s:
        return CellKind.MISSING, None
    if s in DASH_TOKENS:
        if column_is_numeric:
            return CellKind.DASH_ZERO, Decimal(0)
        return CellKind.TEXT, None
    parsed = parse_number(s)
    if isinstance(parsed, Decimal):
        return CellKind.NUMBER, parsed
    if any(d in s for d in ("-", "\u2013", "\u2014")) or not column_is_numeric:
        return (CellKind.UNPARSEABLE if column_is_numeric else CellKind.TEXT), None
    return CellKind.UNPARSEABLE, None


def column_is_numeric(rows: tuple[TableRow, ...], col: int) -> bool:
    """Majority of the OTHER cells (blank and dash tokens aside) parse as numbers."""
    cells = [
        r.cells[col].strip()
        for r in rows
        if col < len(r.cells) and r.cells[col].strip() and r.cells[col].strip() not in DASH_TOKENS
    ]
    if not cells:
        return False
    numeric = sum(1 for c in cells if isinstance(parse_number(c), Decimal))
    return numeric * 2 > len(cells)


# --- scale and currency -----------------------------------------------------

_SCALE_PATTERNS: tuple[tuple[re.Pattern[str], Scale], ...] = (
    (re.compile(r"\bcrores?\b", re.I), Scale.CRORE),
    (re.compile(r"\b(?:lakhs?|lacs?)\b", re.I), Scale.LAKH),
    (re.compile(r"\bmillions?\b|\bmn\b", re.I), Scale.MILLION),
    (re.compile(r"\bbillions?\b|\bbn\b", re.I), Scale.BILLION),
    (re.compile(r"\bthousands?\b|[\u2019']000\b|\b000s\b", re.I), Scale.THOUSAND),
)

_CURRENCY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\u20b9|\brs\.?(?=\s|$|\))|\binr\b|\brupees?\b", re.I), "INR"),
    (re.compile(r"\$|\busd\b|\bu\.?s\.? ?dollars?\b|\bdollars?\b", re.I), "USD"),
)


def detect_scale(text: str) -> Scale | None:
    for rx, scale in _SCALE_PATTERNS:
        if rx.search(text):
            return scale
    return None


def detect_currency(text: str) -> str | None:
    for rx, code in _CURRENCY_PATTERNS:
        if rx.search(text):
            return code
    return None


def resolve_scale(
    cell_text: str, table_text: str, statement_text: str, document_text: str
) -> tuple[Scale, ScaleSource] | None:
    """cell -> table -> statement -> document. Records where it was found."""
    for text, source in (
        (cell_text, ScaleSource.CELL),
        (table_text, ScaleSource.TABLE),
        (statement_text, ScaleSource.STATEMENT),
        (document_text, ScaleSource.DOCUMENT),
    ):
        scale = detect_scale(text)
        if scale is not None:
            return scale, source
    return None


def make_cell_ref(row: TableRow, col: int):
    """A cell-level view of a row SourceRef. Same ref_id; column recorded."""
    return replace(row.ref, col_idx=col, raw_text=row.cells[col])


def table_text(table: ExtractedTable) -> str:
    return " ".join(filter(None, (table.caption or "", *table.header)))


def normalized_cell(
    row: TableRow, col: int, *, scale: Scale, scale_source: ScaleSource, currency: str
) -> Maybe[NormalizedCell] | None:
    """One cell to base units. None means the column is text, not a value."""
    from fincopilot.types import SCALE_MULTIPLIER

    token = row.cells[col] if col < len(row.cells) else ""
    kind, value = classify_cell(token, column_is_numeric=True)
    ref = make_cell_ref(row, col)
    if kind is CellKind.MISSING:
        return Unavailable(UnavailableReason.MISSING_INPUT, "blank cell", refs=(ref.ref_id,))
    if kind is CellKind.UNPARSEABLE:
        return Unavailable(
            UnavailableReason.UNPARSEABLE, f"cannot parse {token!r}", refs=(ref.ref_id,)
        )
    if kind is CellKind.TEXT:
        return None
    assert value is not None
    try:
        scaled = EXACT_CONTEXT.multiply(value, SCALE_MULTIPLIER[scale])
    except Inexact:
        return Unavailable(
            UnavailableReason.UNPARSEABLE,
            f"{token!r} exceeds {EXACT_CONTEXT.prec} significant digits after scaling",
            refs=(ref.ref_id,),
        )
    return NormalizedCell(
        ref=ref,
        raw_token=token,
        value=scaled,
        scale=scale,
        scale_source=scale_source,
        currency=currency,
        dash_zero=kind is CellKind.DASH_ZERO,
    )


# --- document normalisation --------------------------------------------------

# Evidence-based currency conventions when no symbol or code is printed:
# crore/lakh scales exist only in rupee reporting; a Form 10-K reports in USD.
_CONVENTION_INR = re.compile(r"\b(?:crores?|lakhs?|lacs?|ind\s*as)\b", re.I)
_CONVENTION_USD = re.compile(r"\bform\s+10-k\b|\b10-k\b|\bus-?gaap\b", re.I)


def resolve_currency(table_txt: str, statement_txt: str, document_txt: str) -> Maybe[str]:
    """table -> statement -> document, then printed conventions. CONFLICT if two."""
    seen = {c for text in (table_txt, statement_txt) for c in (detect_currency(text),) if c}
    if len(seen) > 1:
        return Unavailable(
            UnavailableReason.CONFLICT, f"two currencies within one statement: {sorted(seen)}"
        )
    for text in (table_txt, statement_txt, document_txt):
        found = detect_currency(text)
        if found:
            return found
    for text in (table_txt, statement_txt, document_txt):
        if _CONVENTION_INR.search(text):
            return "INR"
        if _CONVENTION_USD.search(text):
            return "USD"
    return Unavailable(UnavailableReason.AMBIGUOUS, "no currency stated at any level")


def _normalize_statement(stmt, periods, doc):
    from fincopilot.types import NormalizedTable, ResolvedScale

    table = stmt.table
    table_txt = table_text(table)
    statement_txt = "\n".join(doc.page_text[p - 1] for p in table.pages)
    document_txt = doc.page_text[0] if doc.page_text else ""

    default = resolve_scale("", table_txt, statement_txt, document_txt)
    currency = resolve_currency(table_txt, statement_txt, document_txt)
    if isinstance(currency, Unavailable):
        return currency

    period_cols = [c for (k, c) in periods.columns if k is stmt.kind]
    cells: dict[tuple[str, int], Maybe[NormalizedCell]] = {}
    any_scale = default is not None
    for col in period_cols:
        numeric = column_is_numeric(table.rows, col)
        for row in table.rows:
            token = row.cells[col] if col < len(row.cells) else ""
            resolved = resolve_scale(token, table_txt, statement_txt, document_txt)
            if resolved is None:
                cells[(row.ref.ref_id, col)] = Unavailable(
                    UnavailableReason.AMBIGUOUS,
                    "no scale stated at cell, table, statement, or document level",
                    refs=(row.ref.ref_id,),
                )
                continue
            any_scale = True
            scale, source = resolved
            if not numeric:
                continue
            cell = normalized_cell(row, col, scale=scale, scale_source=source, currency=currency)
            if cell is not None:
                cells[(row.ref.ref_id, col)] = cell

    if not any_scale:
        return Unavailable(
            UnavailableReason.AMBIGUOUS,
            f"{stmt.kind.value}: no scale phrase at cell, table, statement, or document level",
        )
    assert default is not None
    return NormalizedTable(
        kind=stmt.kind,
        basis=stmt.basis,
        table=table,
        scale=ResolvedScale(*default),
        currency=currency,
        cells=cells,
    )


def normalize_document(statements, periods, doc):
    """StatementSet + PeriodMap -> NormalizedTables. Pure."""
    from fincopilot.types import NormalizedTables

    def one(stmt):
        if isinstance(stmt, Unavailable):
            return stmt
        if isinstance(periods, Unavailable):
            return Unavailable(
                UnavailableReason.AMBIGUOUS,
                f"{stmt.kind.value}: periods could not be resolved",
                cause=periods,
            )
        return _normalize_statement(stmt, periods, doc)

    return NormalizedTables(
        income=one(statements.income),
        balance=one(statements.balance),
        cash_flow=one(statements.cash_flow),
    )
