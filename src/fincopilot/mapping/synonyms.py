"""Deterministic label -> canonical concept mapping. Spec 6.1, 6.2.

Tier 1 is an exact canonical label; Tier 2 is a curated alias. Every alias is
an explicit string. There is NO fuzzy matching, edit distance, embedding, or
semantic matching here, and there must never be: that is precisely how these
tools produce confidently wrong numbers.
"""

from __future__ import annotations

import re

from fincopilot.types import CanonicalConcept as C
from fincopilot.types import (
    ExtractionConfidence,
    RowMapping,
    StatementKind,
    Unavailable,
    UnavailableReason,
)
from fincopilot.types import StatementKind as K

# --- statement constraints: a concept may only come from its own statement

CONCEPT_STATEMENT: dict[C, StatementKind] = {
    C.REVENUE: K.INCOME,
    C.GROSS_PROFIT: K.INCOME,
    C.COGS: K.INCOME,
    C.OPERATING_INCOME: K.INCOME,
    C.D_AND_A: K.INCOME,
    C.EBITDA: K.INCOME,
    C.NET_INCOME: K.INCOME,
    C.TOTAL_ASSETS: K.BALANCE,
    C.CURRENT_ASSETS: K.BALANCE,
    C.CASH: K.BALANCE,
    C.TOTAL_LIABILITIES: K.BALANCE,
    C.CURRENT_LIABILITIES: K.BALANCE,
    C.SHORT_TERM_BORROWINGS: K.BALANCE,
    C.LONG_TERM_BORROWINGS: K.BALANCE,
    C.TOTAL_DEBT: K.BALANCE,
    C.EQUITY: K.BALANCE,
    C.OPERATING_CASH_FLOW: K.CASH_FLOW,
    C.CAPEX: K.CASH_FLOW,
    C.FREE_CASH_FLOW: K.CASH_FLOW,
}

# --- Tier 1: canonical labels (normalised form)

CANONICAL: dict[C, tuple[str, ...]] = {
    C.REVENUE: ("revenue", "revenues", "total revenue", "total revenues"),
    C.GROSS_PROFIT: ("gross profit",),
    C.COGS: ("cost of goods sold",),
    C.OPERATING_INCOME: ("operating income", "operating profit"),
    C.D_AND_A: ("depreciation and amortization", "depreciation and amortisation"),
    C.EBITDA: ("ebitda",),
    C.NET_INCOME: ("net income", "net profit"),
    C.TOTAL_ASSETS: ("total assets",),
    C.CURRENT_ASSETS: ("total current assets", "current assets"),
    C.CASH: ("cash and cash equivalents",),
    C.TOTAL_LIABILITIES: ("total liabilities",),
    C.CURRENT_LIABILITIES: ("total current liabilities", "current liabilities"),
    C.SHORT_TERM_BORROWINGS: ("short term borrowings",),
    C.LONG_TERM_BORROWINGS: ("long term borrowings",),
    C.TOTAL_DEBT: ("total debt", "total borrowings"),
    C.EQUITY: ("total equity",),
    C.OPERATING_CASH_FLOW: ("net cash from operating activities", "operating cash flow"),
    C.CAPEX: ("capital expenditure", "capital expenditures"),
    C.FREE_CASH_FLOW: ("free cash flow",),
}

# --- Tier 2: curated per-jurisdiction aliases (normalised form)

INDIAN_ALIASES: dict[C, tuple[str, ...]] = {
    C.REVENUE: ("revenue from operations", "income from operations", "revenue from operations net"),
    C.COGS: ("cost of materials consumed", "cost of goods sold and services rendered"),
    C.OPERATING_INCOME: ("profit from operations", "profit before finance costs and tax"),
    C.D_AND_A: (
        "depreciation and amortisation expense",
        "depreciation and amortization expense",
        "depreciation amortisation and impairment expense",
    ),
    C.NET_INCOME: ("profit for the year", "profit for the period", "profit after tax"),
    C.CASH: ("cash and bank balances",),
    C.SHORT_TERM_BORROWINGS: ("current borrowings",),
    C.LONG_TERM_BORROWINGS: ("non current borrowings",),
    C.EQUITY: (
        "equity attributable to owners of the parent",
        "total equity attributable to owners",
    ),
    C.OPERATING_CASH_FLOW: (
        "net cash generated from operating activities",
        "net cash flow from operating activities",
        "net cash flows from operating activities",
        "net cash generated from operations",
    ),
    C.CAPEX: (
        "purchase of property plant and equipment",
        "payments for property plant and equipment",
        "purchase of property plant and equipment including capital work in progress",
    ),
}

US_ALIASES: dict[C, tuple[str, ...]] = {
    C.REVENUE: ("net sales", "total net sales", "net revenues", "net revenue", "sales"),
    C.COGS: (
        "cost of sales",
        "cost of revenues",
        "cost of revenue",
        "cost of products sold",
        "total cost of revenue",
        "total cost of revenues",
        "total cost of sales",
    ),
    C.GROSS_PROFIT: ("gross margin",),
    C.OPERATING_INCOME: ("income from operations", "operating income loss"),
    C.D_AND_A: ("depreciation depletion and amortization", "depreciation and amortization"),
    C.NET_INCOME: ("net earnings", "net income loss", "net earnings loss"),
    C.SHORT_TERM_BORROWINGS: ("short term debt", "notes payable"),
    C.LONG_TERM_BORROWINGS: ("long term debt", "long term debt net of current portion"),
    C.EQUITY: (
        "total stockholders equity",
        "total shareholders equity",
        "total stockholders equity attributable to parent",
    ),
    C.OPERATING_CASH_FLOW: (
        "net cash provided by operating activities",
        "cash provided by operating activities",
        "net cash provided by used in operating activities",
        "cash generated by operating activities",
        "net cash flows from operating activities",
        "net cash from operations",
    ),
    C.CAPEX: (
        "purchases of property and equipment",
        "purchases of property plant and equipment",
        "purchase of property and equipment",
        "additions to property and equipment",
        "payments for acquisition of property plant and equipment",
        "purchases of property plant and equipment net",
    ),
}

# --- Negative lists: known semantic traps. As important as the positives.

BLOCKED: dict[C, frozenset[str]] = {
    # Ind-AS "Total income" includes other income; mapping it overstates the topline.
    C.REVENUE: frozenset({"total income", "other income", "total revenue and other income"}),
    C.TOTAL_LIABILITIES: frozenset(
        {
            "total current liabilities",
            "total non current liabilities",
            "total equity and liabilities",
        }
    ),
    C.CASH: frozenset(
        {
            "cash and cash equivalents at the end of the year",
            "cash and cash equivalents at end of period",
            "cash and cash equivalents at the end of the period",
            "cash and cash equivalents at the beginning of the year",
        }
    ),
    C.EQUITY: frozenset(
        {"total equity and liabilities", "total liabilities and stockholders equity"}
    ),
    C.OPERATING_INCOME: frozenset({"profit before tax", "income before income taxes"}),
    C.NET_INCOME: frozenset({"profit before tax", "income before income taxes"}),
}

# A "(a)" closing a label is a footnote reference ("Total assets(a)"); a
# leading "(a)" is list numbering, handled by _LEADING_NUMBERING.
_FOOTNOTE = re.compile(
    r"[*\u2020\u2021\u00a7\u00b9\u00b2\u00b3]+|\(note \d+[a-z]?\)|\(refer note [^)]*\)"
    r"|(?:\([a-z]\))+$"
)
_LEADING_NUMBERING = re.compile(r"^(?:\(?[0-9ivx]+[.)]|\(?[a-z][.)])\s+")
_PUNCT = re.compile(r"[^\w\s]")


def normalize_label(label: str) -> str:
    """Case, footnote markers, numbering, punctuation, and whitespace removed."""
    s = label.strip().lower()
    s = _FOOTNOTE.sub(" ", s)
    s = _LEADING_NUMBERING.sub("", s)
    s = s.replace("&", " and ")
    s = s.replace("'", "")
    s = _PUNCT.sub(" ", s)
    return " ".join(s.split())


def _lookup(norm: str, kind: StatementKind) -> tuple[C, ExtractionConfidence] | None:
    for concept, labels in CANONICAL.items():
        if CONCEPT_STATEMENT[concept] is kind and norm in labels:
            return concept, ExtractionConfidence.EXACT_MATCH
    for table in (INDIAN_ALIASES, US_ALIASES):
        for concept, labels in table.items():
            if CONCEPT_STATEMENT[concept] is kind and norm in labels:
                return concept, ExtractionConfidence.SYNONYM_MATCH
    return None


def match_label(label: str, kind: StatementKind) -> tuple[C, ExtractionConfidence] | None:
    """Tier 1 then Tier 2, restricted to the statement the concept may come from."""
    norm = normalize_label(label)
    if not norm:
        return None
    hit = _lookup(norm, kind)
    if hit is None:
        return None
    if norm in BLOCKED.get(hit[0], frozenset()):
        return None
    return hit


# --- rows -------------------------------------------------------------------


def _is_section_header(table, row) -> bool:
    """A row with a label and nothing but blanks in the period columns.

    A row whose cells failed to parse is NOT a section header: it must stay a
    mapping candidate so the failure reaches the user as UNPARSEABLE."""
    return not any(
        k[0] == row.ref.ref_id and not _is_blank(cell) for k, cell in table.cells.items()
    )


def _is_blank(cell) -> bool:
    return isinstance(cell, Unavailable) and cell.reason is UnavailableReason.MISSING_INPUT


def map_rows(normalized) -> tuple[RowMapping, ...]:
    """Tier 1/2 over every located statement. A bare Total resolves by section."""
    out: list[RowMapping] = []
    for table in (normalized.income, normalized.balance, normalized.cash_flow):
        if not hasattr(table, "cells"):
            continue  # Unavailable statement
        section = ""
        for row in table.table.rows:
            if _is_section_header(table, row):
                section = normalize_label(row.label)
                continue
            label = row.label
            if normalize_label(label) == "total" and section:
                label = f"total {section}"
            hit = match_label(label, table.kind)
            if hit is None:
                continue
            concept, confidence = hit
            out.append(RowMapping(concept, row.ref.ref_id, table.kind, confidence))
    return tuple(out)
