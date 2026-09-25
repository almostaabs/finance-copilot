"""Statement location, scope scoring, and multi-page stitching. Spec 4.3, 4.4."""

from dataclasses import replace
from pathlib import Path

import pytest

from fincopilot.extract.anchors import Scope, anchor_lines, find_anchors, is_sec_annual_report
from fincopilot.extract.locate import locate_statements, stitch_tables
from fincopilot.extract.pdf import extract_pdf, validate_input
from fincopilot.types import (
    ExtractedTable,
    RawDocument,
    StatementBasis,
    StatementKind,
    TableRow,
    UnavailableReason,
    is_unavailable,
)
from tests.helpers import make_source_ref

FIXTURES = Path(__file__).parent / "fixtures"


def _doc(name: str) -> RawDocument:
    data = (FIXTURES / name).read_bytes()
    return extract_pdf(data, validate_input(data))


@pytest.fixture(scope="module")
def golden_indian():
    return locate_statements(_doc("golden_indian.pdf"))


@pytest.fixture(scope="module")
def golden_us():
    return locate_statements(_doc("golden_us.pdf"))


def test_golden_indian_selects_consolidated_over_standalone(golden_indian):
    s = golden_indian
    assert s.basis is StatementBasis.CONSOLIDATED
    assert s.income.table.first_page == 41
    assert s.balance.table.first_page == 42
    assert s.cash_flow.table.first_page == 43
    # Not the standalone figures on pages 44-46.
    assert s.income.table.rows[0].cells[1] == "12,450.00"


def test_golden_us_locates_all_three_us_gaap_headings(golden_us):
    s = golden_us
    assert s.basis is StatementBasis.CONSOLIDATED
    assert s.income.table.first_page == 26
    assert s.balance.table.first_page == 27
    assert s.cash_flow.table.first_page == 28
    assert s.income.kind is StatementKind.INCOME


def test_standalone_only_falls_back_and_labels_loudly():
    s = locate_statements(_doc("standalone_only.pdf"))
    assert s.basis is StatementBasis.STANDALONE_FALLBACK
    assert s.income.basis is StatementBasis.STANDALONE_FALLBACK
    assert s.income.table.rows[0].cells[1] == "3,420.00"
    assert s.balance.table.first_page == 5
    assert is_unavailable(s.cash_flow)
    assert s.cash_flow.reason is UnavailableReason.NOT_LOCATED


def test_stitched_balance_sheet_merges_and_keeps_true_pages():
    s = locate_statements(_doc("stitched.pdf"))
    table = s.balance.table
    assert table.pages == (5, 6)
    assert table.header == ("Particulars", "As at 31 March 2024", "As at 31 March 2023")
    labels = [r.label for r in table.rows]
    assert labels[0] == "Property, plant and equipment"
    assert labels[6] == "Other current assets"
    assert labels[-1] == "Total equity and liabilities"
    assert table.rows[5].ref.page == 5
    assert table.rows[6].ref.page == 6
    assert table.rows[6].ref.ref_id == "page_6_table_0_row_0"
    total_assets = next(r for r in table.rows if r.label == "Total assets")
    assert total_assets.ref.page == 6


def test_hostile_locates_what_exists_and_reports_the_rest_not_located():
    s = locate_statements(_doc("hostile.pdf"))
    assert s.basis is StatementBasis.CONSOLIDATED
    assert s.income.table.first_page == 3
    assert s.balance.table.first_page == 4
    assert is_unavailable(s.cash_flow)
    # The 500-row note must not be mistaken for a cash flow statement.
    assert s.cash_flow.reason is UnavailableReason.NOT_LOCATED


def test_missing_statement_does_not_sink_the_others(golden_indian):
    # Every statement present here; the contract still allows partial results.
    assert not is_unavailable(golden_indian.income)


# --- stitching rules, in isolation


def _table(
    page: int, header: tuple[str, ...], labels: list[str], ncols: int = 3, table_idx: int = 0
):
    rows = tuple(
        TableRow(
            ref=make_source_ref(page=page, table_idx=table_idx, row_idx=i, row_label=lbl),
            label=lbl,
            cells=(lbl,) + ("1.00",) * (ncols - 1),
        )
        for i, lbl in enumerate(labels)
    )
    return ExtractedTable(f"page_{page}_table_{table_idx}", page, (page,), header, rows, None)


HDR = ("Particulars", "FY2024", "FY2023")


def test_stitch_requires_consecutive_pages():
    a = _table(5, HDR, ["Total assets"])
    b = _table(7, (), ["Total equity"])
    assert len(stitch_tables((a, b))) == 2


def test_stitch_requires_matching_column_count():
    a = _table(5, HDR, ["Total assets"], ncols=3)
    b = _table(6, (), ["Total equity"], ncols=4)
    assert len(stitch_tables((a, b))) == 2


def test_stitch_accepts_no_header_or_the_identical_header_only():
    a = _table(5, HDR, ["Total assets"])
    same = _table(6, HDR, ["Total equity"])
    (merged,) = stitch_tables((a, same))
    assert merged.pages == (5, 6)
    other = _table(6, ("Particulars", "2019", "2018"), ["Total equity"])
    assert len(stitch_tables((a, other))) == 2


def test_stitch_looks_past_an_unrelated_table_on_the_same_page():
    a = _table(5, HDR, ["Total assets"])
    noise = _table(5, ("x", "2001", "2000"), ["Note"], table_idx=1)
    b = _table(6, (), ["Total equity"])
    out = stitch_tables((a, noise, b))
    assert len(out) == 2
    assert next(t for t in out if t.table_id == a.table_id).pages == (5, 6)


def test_stitch_merges_when_all_conditions_hold():
    a = _table(5, HDR, ["Total assets"])
    b = _table(6, (), ["Total equity"])
    (merged,) = stitch_tables((a, b))
    assert merged.pages == (5, 6)
    assert merged.header == HDR
    assert [r.ref.page for r in merged.rows] == [5, 6]


def test_stitch_chains_across_three_pages():
    a = _table(5, HDR, ["r1"])
    b = _table(6, (), ["r2"])
    c = _table(7, (), ["r3"])
    (merged,) = stitch_tables((a, b, c))
    assert merged.pages == (5, 6, 7)
    assert [r.ref.page for r in merged.rows] == [5, 6, 7]


def test_stitch_requires_approximately_matching_column_positions():
    a = _table(5, HDR, ["Total assets"])
    b = _table(6, (), ["Total equity"])
    a = ExtractedTable(a.table_id, 5, (5,), a.header, a.rows, None, col_x=(40.0, 250.0, 400.0))
    b = ExtractedTable(b.table_id, 6, (6,), b.header, b.rows, None, col_x=(40.0, 300.0, 400.0))
    assert len(stitch_tables((a, b))) == 2


def test_stitch_refuses_a_page_that_starts_a_different_statement():
    a = _table(5, HDR, ["Total assets"])
    b = _table(6, HDR, ["Net income"])
    bs = "Consolidated Balance Sheet" + chr(10) + "1 2"
    cf = "Consolidated Statement of Cash Flows" + chr(10) + "1 2"
    assert len(stitch_tables((a, b), ("",) * 4 + (bs, cf))) == 2
    assert len(stitch_tables((a, b), ("",) * 4 + (bs, bs))) == 1
    assert len(stitch_tables((a, b), ("",) * 4 + (bs, "just numbers"))) == 1


# UPS writes the scope inside the title: "STATEMENTS OF CONSOLIDATED INCOME".
@pytest.mark.parametrize(
    ("heading", "kind"),
    [
        ("STATEMENTS OF CONSOLIDATED INCOME", StatementKind.INCOME),
        ("Statements of Consolidated Operations", StatementKind.INCOME),
        ("STATEMENTS OF CONSOLIDATED BALANCE SHEETS", StatementKind.BALANCE),
        ("Statement of Consolidated Financial Position", StatementKind.BALANCE),
        ("STATEMENTS OF CONSOLIDATED CASH FLOWS", StatementKind.CASH_FLOW),
    ],
)
def test_statements_of_consolidated_heading_is_a_consolidated_anchor(heading, kind):
    assert find_anchors(heading) == [(kind, Scope.CONSOLIDATED)]
    assert anchor_lines(heading) == (heading.lower(),)


def test_statements_of_consolidated_forms_stay_literal():
    assert find_anchors("STATEMENTS OF CONSOLIDATED COMPREHENSIVE INCOME") == []
    assert find_anchors("STATEMENTS OF CONSOLIDATED SHAREOWNERS EQUITY") == []


# --- 10-K evidence: unprefixed statements under a Form 10-K cover are consolidated

COVER_10K = "\n".join(
    (
        "UNITED STATES",
        "SECURITIES AND EXCHANGE COMMISSION",
        "Washington, D.C.  20549",
        "FORM 10-K",
        "ANNUAL REPORT PURSUANT TO SECTION 13 OR 15(d)",
    )
)


@pytest.mark.parametrize(
    "text",
    [
        COVER_10K,
        COVER_10K.replace("FORM 10-K", "Form 10" + chr(0x2011) + "K"),
        COVER_10K.replace("Washington, D.C.  20549", "Washington D.C. 20549"),
    ],
)
def test_a_10k_cover_page_is_sec_annual_report_evidence(text):
    assert is_sec_annual_report(text)


@pytest.mark.parametrize(
    "text",
    [
        COVER_10K.replace("FORM 10-K", "FORM 10-Q"),
        # Prose names the form and the commission, but only a cover prints the address.
        "As described in our Form 10-K filed with the Securities and Exchange Commission, "
        "revenue grew in every segment.",
        "Annual Report 2024. Consolidated Statements of Operations.",
    ],
)
def test_text_without_a_10k_cover_is_not_sec_annual_report_evidence(text):
    assert not is_sec_annual_report(text)


@pytest.fixture(scope="module")
def unprefixed_10k():
    return _doc("unprefixed_10k.pdf")


def test_unprefixed_statements_in_a_10k_are_consolidated(unprefixed_10k):
    s = locate_statements(unprefixed_10k)
    assert s.basis is StatementBasis.CONSOLIDATED
    assert s.income.basis is StatementBasis.CONSOLIDATED
    assert (s.income.table.first_page, s.balance.table.first_page) == (2, 3)
    assert s.cash_flow.table.first_page == 4


def test_a_10k_cover_found_deep_in_the_document_still_counts(unprefixed_10k):
    # Page 30: the cover is scanned for on every page, not just the first few.
    texts = ("",) + unprefixed_10k.page_text[1:] + ("",) * 25 + (unprefixed_10k.page_text[0],)
    s = locate_statements(replace(unprefixed_10k, page_text=texts, page_count=len(texts)))
    assert len(texts) == 30
    assert s.basis is StatementBasis.CONSOLIDATED


def test_unprefixed_statements_without_10k_cover_stay_standalone_fallback(unprefixed_10k):
    texts = ("Meridian Systems, Inc. Annual Report 2024", *unprefixed_10k.page_text[1:])
    s = locate_statements(replace(unprefixed_10k, page_text=texts))
    assert s.basis is StatementBasis.STANDALONE_FALLBACK
    assert s.income.basis is StatementBasis.STANDALONE_FALLBACK


def test_explicit_standalone_is_never_promoted_in_a_10k(unprefixed_10k):
    texts = tuple(
        t.replace("INCOME STATEMENTS", "STANDALONE INCOME STATEMENTS")
        .replace("BALANCE SHEETS", "STANDALONE BALANCE SHEETS")
        .replace("CASH FLOWS STATEMENTS", "STANDALONE CASH FLOWS STATEMENTS")
        for t in unprefixed_10k.page_text
    )
    assert is_sec_annual_report(texts[0])
    s = locate_statements(replace(unprefixed_10k, page_text=texts))
    assert s.basis is StatementBasis.STANDALONE_FALLBACK
