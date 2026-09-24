"""Deterministic label mapping. Spec 6.1, 6.2. No fuzzy matching anywhere."""

import pytest

from fincopilot.mapping.synonyms import match_label, normalize_label
from fincopilot.types import CanonicalConcept as C
from fincopilot.types import ExtractionConfidence as X
from fincopilot.types import StatementKind as K


@pytest.mark.parametrize(
    "raw, norm",
    [
        ("Revenue from operations", "revenue from operations"),
        ("  Total   Assets  ", "total assets"),
        ("Net income:", "net income"),
        ("Revenue*", "revenue"),
        ("Revenue (Note 4)", "revenue"),
        ("1. Revenue from operations", "revenue from operations"),
        ("(a) Cost of materials consumed", "cost of materials consumed"),
        ("Total assets(a)", "total assets"),
        ("Total liabilities (a)(b)", "total liabilities"),
        ("Total stockholders' equity", "total stockholders equity"),
        ("Depreciation & amortisation", "depreciation and amortisation"),
        (
            "Net cash generated from operating activities\u00b9",
            "net cash generated from operating activities",
        ),
    ],
)
def test_normalize_label(raw, norm):
    assert normalize_label(raw) == norm


@pytest.mark.parametrize(
    "label, kind, concept, conf",
    [
        ("Revenue", K.INCOME, C.REVENUE, X.EXACT_MATCH),
        ("Revenue from operations", K.INCOME, C.REVENUE, X.SYNONYM_MATCH),
        ("Net sales", K.INCOME, C.REVENUE, X.SYNONYM_MATCH),
        ("Cost of materials consumed", K.INCOME, C.COGS, X.SYNONYM_MATCH),
        ("Cost of sales", K.INCOME, C.COGS, X.SYNONYM_MATCH),
        ("Gross profit", K.INCOME, C.GROSS_PROFIT, X.EXACT_MATCH),
        ("Profit from operations", K.INCOME, C.OPERATING_INCOME, X.SYNONYM_MATCH),
        ("Operating income", K.INCOME, C.OPERATING_INCOME, X.EXACT_MATCH),
        ("Depreciation and amortisation expense", K.INCOME, C.D_AND_A, X.SYNONYM_MATCH),
        ("Depreciation and amortization", K.INCOME, C.D_AND_A, X.EXACT_MATCH),
        ("Profit for the year", K.INCOME, C.NET_INCOME, X.SYNONYM_MATCH),
        ("Net income", K.INCOME, C.NET_INCOME, X.EXACT_MATCH),
        ("Total assets", K.BALANCE, C.TOTAL_ASSETS, X.EXACT_MATCH),
        ("Total current assets", K.BALANCE, C.CURRENT_ASSETS, X.EXACT_MATCH),
        ("Cash and cash equivalents", K.BALANCE, C.CASH, X.EXACT_MATCH),
        ("Total liabilities", K.BALANCE, C.TOTAL_LIABILITIES, X.EXACT_MATCH),
        ("Total current liabilities", K.BALANCE, C.CURRENT_LIABILITIES, X.EXACT_MATCH),
        ("Short-term borrowings", K.BALANCE, C.SHORT_TERM_BORROWINGS, X.EXACT_MATCH),
        ("Short-term debt", K.BALANCE, C.SHORT_TERM_BORROWINGS, X.SYNONYM_MATCH),
        ("Long-term borrowings", K.BALANCE, C.LONG_TERM_BORROWINGS, X.EXACT_MATCH),
        ("Long-term debt", K.BALANCE, C.LONG_TERM_BORROWINGS, X.SYNONYM_MATCH),
        ("Total equity", K.BALANCE, C.EQUITY, X.EXACT_MATCH),
        ("Total stockholders' equity", K.BALANCE, C.EQUITY, X.SYNONYM_MATCH),
        (
            "Net cash generated from operating activities",
            K.CASH_FLOW,
            C.OPERATING_CASH_FLOW,
            X.SYNONYM_MATCH,
        ),
        (
            "Net cash provided by operating activities",
            K.CASH_FLOW,
            C.OPERATING_CASH_FLOW,
            X.SYNONYM_MATCH,
        ),
        ("Purchase of property, plant and equipment", K.CASH_FLOW, C.CAPEX, X.SYNONYM_MATCH),
        ("Purchases of property and equipment", K.CASH_FLOW, C.CAPEX, X.SYNONYM_MATCH),
        ("Free cash flow", K.CASH_FLOW, C.FREE_CASH_FLOW, X.EXACT_MATCH),
    ],
)
def test_positive_matches(label, kind, concept, conf):
    assert match_label(label, kind) == (concept, conf)


@pytest.mark.parametrize(
    "label, kind",
    [
        ("Total income", K.INCOME),  # includes other income; never revenue
        ("Total current liabilities", K.INCOME),  # wrong statement
        ("Revenue from operations", K.BALANCE),  # wrong statement
        ("Cash and cash equivalents at the end of the year", K.CASH_FLOW),
        ("Cash and cash equivalents", K.CASH_FLOW),  # cash only from the balance sheet
        ("Other income", K.INCOME),
        ("Revenues from operations", K.INCOME),  # one letter off: no fuzzy matching
        ("Revenu from operations", K.INCOME),
        ("Total", K.BALANCE),  # bare Total resolves only by section context
        ("Miscellaneous expense item 001", K.INCOME),
    ],
)
def test_negative_and_structural_rejections(label, kind):
    assert match_label(label, kind) is None


def test_total_current_liabilities_never_becomes_total_liabilities():
    assert match_label("Total current liabilities", K.BALANCE)[0] is C.CURRENT_LIABILITIES
