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
# ASCII digits only ([0-9], not backslash-d) and years 1900-2199.
_RANGE = re.compile(
    r"(?<![0-9])((?:19|20|21)[0-9]{2})\s*[-\u2013/]\s*((?:19|20|21)?[0-9]{2})(?![0-9])"
)
_YEAR = re.compile(r"(?<![0-9])((?:19|20|21)[0-9]{2})(?![0-9])")


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


# --- T1.1-g: "Fiscal YYYY" headers beside date headers ----------------------
#
# A retailer may head its income and cash-flow statements "Fiscal 2025" and its
# balance sheet "February 1, 2026". The same period then carries two year
# labels. The fiscal label is reconciled only from one sentence or table row
# that binds it to an end date printed in a balance-sheet column; anything
# less leaves the whole document AMBIGUOUS. No date arithmetic.

_MONTHS = "january|february|march|april|may|june|july|august|september|october|november|december"
_MONTH_DAY = re.compile(rf"\b({_MONTHS})\s+([0-9]{{1,2}}),", re.I)
_FISCAL = re.compile(r"\bfiscal\b", re.I)
_BOUND_DATE = rf"({_MONTHS})\s+([0-9]{{1,2}}),\s*((?:19|20|21)[0-9]{{2}})"
_BINDINGS = (
    # "fiscal 2025 | Fiscal year ended February 1, 2026"
    (re.compile(rf"\bfiscal\s+((?:19|20|21)[0-9]{{2}})\b.*?\bended\s+{_BOUND_DATE}", re.I), 1, 2),
    # "fiscal year ended February 1, 2026 ("fiscal 2025")"
    (re.compile(rf"\bended\s+{_BOUND_DATE}.*?\bfiscal\s+((?:19|20|21)[0-9]{{2}})\b", re.I), 4, 1),
)
_FY_LABEL = re.compile(r"\bfiscal\s+(?:19|20|21)[0-9]{2}\b", re.I)
_ANY_DATE = re.compile(_BOUND_DATE, re.I)
_SENTENCE_END = re.compile(r"(?<=[.;])\s+")

_Date = tuple[str, int, int]  # month (lower case), day, year


def _header_block(stmt, page_text: tuple[str, ...]) -> str | None:
    """The page line printing the statement's header years, plus the line above."""
    years = [c.strip() for c in stmt.table.header[1:]]
    lines = page_text[stmt.table.first_page - 1].splitlines()
    for i, line in enumerate(lines):
        if _YEAR.findall(line) == years:
            return "\n".join(lines[max(0, i - 1) : i + 1])
    return None


def _header_dates(stmt, block: str) -> list[_Date] | None:
    """One printed month-day per column, paired in order with the column years."""
    days = _MONTH_DAY.findall(block)
    years = [int(c.strip()) for c in stmt.table.header[1:]]
    if len(days) != len(years):
        return None
    return [(m.lower(), int(d), y) for (m, d), y in zip(days, years, strict=True)]


def _bindings(page_text: tuple[str, ...]) -> list[tuple[int, _Date, str, int]]:
    """(fiscal year, end date, the sentence, page) for every one-sentence binding."""
    out = []
    for page_no, text in enumerate(page_text, start=1):
        for line in text.splitlines():
            for sentence in _SENTENCE_END.split(line):
                if len(_FY_LABEL.findall(sentence)) != 1 or len(_ANY_DATE.findall(sentence)) != 1:
                    continue  # one fiscal label and one date, or no binding
                for rx, fy_group, date_group in _BINDINGS:
                    m = rx.search(sentence)
                    if m:
                        month, day, year = m.group(date_group, date_group + 1, date_group + 2)
                        date = (month.lower(), int(day), int(year))
                        out.append((int(m.group(fy_group)), date, sentence.strip(), page_no))
                        break
    return out


def reconcile_fiscal_years(
    statements: StatementSet, periods: Maybe[PeriodMap], page_text: tuple[str, ...]
) -> Maybe[PeriodMap]:
    """Relabel date-headed columns by fiscal year when the document binds them."""
    if is_unavailable(periods):
        return periods
    fiscal, dated = [], []
    for stmt in (statements.income, statements.balance, statements.cash_flow):
        if is_unavailable(stmt):
            continue
        block = _header_block(stmt, page_text)
        if block is None:
            continue
        dates = _header_dates(stmt, block)
        if dates is not None:
            dated.append((stmt.kind, dates))
        elif len(_FISCAL.findall(block)) >= len(stmt.table.header) - 1:
            fiscal.append(stmt.kind)
    if not fiscal or not dated:
        return periods  # consistent headers: untouched

    mixed = (
        f"{', '.join(k.value for k in fiscal)} headed by fiscal year, "
        f"{', '.join(k.value for k, _ in dated)} by end date"
    )
    found = _bindings(page_text)
    by_fy: dict[int, set[_Date]] = {}
    by_date: dict[_Date, set[int]] = {}
    for fy, date, _, _ in found:
        by_fy.setdefault(fy, set()).add(date)
        by_date.setdefault(date, set()).add(fy)
    clash = [b for b in found if len(by_fy[b[0]]) > 1 or len(by_date[b[1]]) > 1]
    if clash:
        quoted = "; ".join(f"p{p}: {s!r}" for _, _, s, p in clash)
        return Unavailable(
            UnavailableReason.AMBIGUOUS, f"{mixed}; conflicting fiscal-year bindings: {quoted}"
        )

    columns = dict(periods.columns)
    for kind, dates in dated:
        for col_idx, date in enumerate(dates, start=1):
            hit = next((b for b in found if b[1] == date), None)
            if hit is None:
                return Unavailable(
                    UnavailableReason.AMBIGUOUS,
                    f"{mixed}; no sentence binds {date[0].title()} {date[1]}, {date[2]} "
                    "to a fiscal year",
                )
            fy, _, sentence, page = hit
            columns[(kind, col_idx)] = Period(
                end_year=fy, label=f"fiscal {fy} (p{page}: {sentence!r})"
            )
    for kind, dates in dated:
        years = [columns[(kind, c)].end_year for c in range(1, len(dates) + 1)]
        if len(set(years)) != len(years):
            return Unavailable(
                UnavailableReason.AMBIGUOUS, f"{mixed}; two {kind.value} columns bind one year"
            )
    ordered = tuple(sorted(set(columns.values()), reverse=True))
    return PeriodMap(columns=columns, ordered=ordered)
