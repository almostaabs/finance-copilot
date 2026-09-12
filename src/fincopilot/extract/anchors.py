"""Text-pass heuristics shared by extraction and location.

Pure functions over page text and cell strings. No I/O, no imports from later
pipeline stages.
"""

from __future__ import annotations

import re
from enum import Enum

from fincopilot.types import StatementKind


class Scope(Enum):
    CONSOLIDATED = "consolidated"
    STANDALONE = "standalone"  # explicit "Standalone" prefix
    UNPREFIXED = "unprefixed"  # single-entity reports; treated as standalone scope


_KIND_PATTERNS: dict[StatementKind, tuple[str, ...]] = {
    StatementKind.INCOME: (
        r"statements? of profit and loss",
        r"statements? of operations",
        r"statements? of income",
        r"income statements?",
        r"statements? of comprehensive income",
    ),
    StatementKind.BALANCE: (
        r"balance sheets?",
        r"statements? of financial position",
    ),
    StatementKind.CASH_FLOW: (
        r"statements? of cash flows?",
        r"cash flow statements?",
    ),
}

_ANCHOR_RE = {
    kind: re.compile(r"^\s*(?:(consolidated|standalone)\s+)?(?:" + "|".join(pats) + r")\b", re.I)
    for kind, pats in _KIND_PATTERNS.items()
}

_YEAR = re.compile(r"(?<![0-9])(?:19|20|21)[0-9]{2}(?![0-9])")
_AMOUNT = re.compile(r"^\(?[-+]?\d[\d,]*(?:\.\d+)?\)?-?$")
_NUMERIC_TOKEN = re.compile(r"\(?\d[\d,]*(?:\.\d+)?\)?")

MIN_NUMERIC_TOKENS = 8
MIN_NUMERIC_FRACTION = 0.25


def find_anchors(text: str) -> list[tuple[StatementKind, Scope]]:
    """Heading lines that name a financial statement, with their scope."""
    hits: list[tuple[StatementKind, Scope]] = []
    for line in text.splitlines():
        for kind, rx in _ANCHOR_RE.items():
            m = rx.match(line)
            if not m:
                continue
            prefix = (m.group(1) or "").lower()
            if prefix == "consolidated":
                scope = Scope.CONSOLIDATED
            elif prefix == "standalone":
                scope = Scope.STANDALONE
            else:
                scope = Scope.UNPREFIXED
            hits.append((kind, scope))
    return hits


def is_amount_token(cell: str) -> bool:
    """Digits with grouping, decimals, parentheses or sign. Never a bare year."""
    s = cell.strip()
    if not s or not _AMOUNT.match(s):
        return False
    return _YEAR.fullmatch(s) is None


def looks_like_header(cells: list[str]) -> bool:
    """A header row names periods and carries no amounts."""
    tail = [c for c in cells[1:] if c.strip()]
    if not tail:
        return False
    if any(is_amount_token(c) for c in tail):
        return False
    return any(_YEAR.search(c) for c in tail)


def numeric_density(text: str) -> tuple[int, float]:
    tokens = text.split()
    if not tokens:
        return 0, 0.0
    numeric = sum(1 for t in tokens if _NUMERIC_TOKEN.fullmatch(t))
    return numeric, numeric / len(tokens)


def is_numeric_dense(text: str) -> bool:
    count, fraction = numeric_density(text)
    return count >= MIN_NUMERIC_TOKENS and fraction >= MIN_NUMERIC_FRACTION


def candidate_table_pages(page_texts: list[str]) -> list[int]:
    """1-based pages worth a table pass: anchor hits +-1, plus numeric-dense pages."""
    n = len(page_texts)
    chosen: set[int] = set()
    for i, text in enumerate(page_texts, start=1):
        if find_anchors(text):
            chosen.update(p for p in (i - 1, i, i + 1) if 1 <= p <= n)
        elif is_numeric_dense(text):
            chosen.add(i)
    return sorted(chosen)
