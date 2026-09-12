"""Column headers to normalised periods. Spec 5.1.

Order is decided by parsed years, never by column position. Two columns that
resolve to the same year, or a header that yields no year, make the whole
document AMBIGUOUS: no guessing.
"""

from __future__ import annotations

import re

from fincopilot.types import (
    Maybe,
    Period,
    PeriodMap,
    StatementKind,
    StatementSet,
    Unavailable,
    UnavailableReason,
    is_unavailable,
)

# "FY 2023-24", "2023-2024", "FY2023-24": the END of the range is the period.
_RANGE = re.compile(r"(?<!\d)((?:19|20)\d{2})\s*[-\u2013/]\s*((?:19|20)?\d{2})(?!\d)")
_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")


def parse_period(label: str) -> Maybe[Period]:
    """One header cell to a Period. Original text is preserved as the label."""
    m = _RANGE.search(label)
    if m:
        start, end = m.group(1), m.group(2)
        end_year = int(end) if len(end) == 4 else int(start[:2] + end)
        if end_year < int(start):  # "2023-99" style rollovers are not periods
            end_year = int(start[:2] + end) + 100
        return Period(end_year=end_year, label=label)
    m = _YEAR.search(label)
    if m:
        return Period(end_year=int(m.group(1)), label=label)
    return Unavailable(UnavailableReason.AMBIGUOUS, f"header cell yields no year: {label!r}")


def detect_periods(statements: StatementSet) -> Maybe[PeriodMap]:
    """Per-statement column map plus a document-wide ordered union."""
    columns: dict[tuple[StatementKind, int], Period] = {}
    for stmt in (statements.income, statements.balance, statements.cash_flow):
        if is_unavailable(stmt):
            continue
        header = stmt.table.header
        if len(header) < 2:
            return Unavailable(
                UnavailableReason.AMBIGUOUS,
                f"{stmt.kind.value} statement has no header row to read periods from",
            )
        seen: dict[Period, int] = {}
        for col_idx, cell in enumerate(header[1:], start=1):
            period = parse_period(cell)
            if is_unavailable(period):
                return Unavailable(
                    UnavailableReason.AMBIGUOUS,
                    f"{stmt.kind.value} column {col_idx}: {period.detail}",
                    cause=period,
                )
            if period in seen:
                return Unavailable(
                    UnavailableReason.AMBIGUOUS,
                    f"{stmt.kind.value} columns {seen[period]} and {col_idx} both resolve "
                    f"to {period.end_year}",
                )
            seen[period] = col_idx
            columns[(stmt.kind, col_idx)] = period

    ordered = tuple(sorted(set(columns.values()), reverse=True))
    return PeriodMap(columns=columns, ordered=ordered)
