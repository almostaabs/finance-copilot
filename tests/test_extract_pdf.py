"""Ingestion gate and raw extraction. Spec section 4.1, 4.2."""

from pathlib import Path

import pytest

from fincopilot.extract.pdf import (
    DocumentRef,
    FileTooLarge,
    NotAPDF,
    ScannedPDFUnsupported,
    TooManyPages,
    UnreadablePDF,
    extract_pdf,
    validate_input,
)
from fincopilot.types import RawDocument, SourceRef

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# --- validate_input: cheapest rejection first, before any parse


def test_validate_input_rejects_oversized_before_looking_at_content():
    with pytest.raises(FileTooLarge):
        validate_input(b"%PDF-1.7 " + b"x" * 100, max_bytes=50)


def test_validate_input_rejects_bad_magic_bytes():
    # MIME type is never consulted. The bytes decide.
    with pytest.raises(NotAPDF):
        validate_input(b"<html>not a pdf</html>")


def test_validate_input_mints_an_opaque_document_id():
    ref = validate_input(_load("golden_us.pdf"))
    assert isinstance(ref, DocumentRef)
    assert len(ref.document_id) == 32  # uuid4 hex; never the user filename
    assert ref.size_bytes == len(_load("golden_us.pdf"))


def test_document_id_is_never_derived_from_a_user_supplied_name():
    a = validate_input(_load("golden_us.pdf"))
    b = validate_input(_load("golden_us.pdf"))
    assert a.document_id != b.document_id


# --- extract_pdf: gate order, then extraction


def test_corrupt_pdf_raises_unreadable():
    data = b"%PDF-1.7\n" + b"garbage" * 50
    ref = validate_input(data)
    with pytest.raises(UnreadablePDF):
        extract_pdf(data, ref)


def test_page_cap_is_enforced_before_any_text_extraction():
    data = _load("golden_us.pdf")  # 34 pages
    ref = validate_input(data)
    with pytest.raises(TooManyPages):
        extract_pdf(data, ref, max_pages=10)


def test_scanned_pdf_is_rejected_explicitly():
    data = _load("scanned.pdf")
    ref = validate_input(data)
    with pytest.raises(ScannedPDFUnsupported):
        extract_pdf(data, ref)


def test_extract_pdf_returns_page_text_for_every_page():
    data = _load("golden_indian.pdf")
    doc = extract_pdf(data, validate_input(data))
    assert isinstance(doc, RawDocument)
    assert doc.page_count == 60
    assert len(doc.page_text) == 60
    assert "Consolidated Statement of Profit and Loss" in doc.page_text[40]


def test_extract_pdf_extracts_tables_on_statement_pages_with_true_refs():
    data = _load("golden_indian.pdf")
    doc = extract_pdf(data, validate_input(data))
    by_page = {t.first_page: t for t in doc.tables}
    assert {41, 42, 43, 44, 45, 46} <= set(by_page)

    income = by_page[41]
    assert income.header == ("Particulars", "FY 2023-24", "FY 2022-23")
    assert income.rows[0].label == "Revenue from operations"
    assert income.rows[0].cells == ("Revenue from operations", "12,450.00", "10,980.00")

    ref = income.rows[0].ref
    assert isinstance(ref, SourceRef)
    assert ref.ref_id == "page_41_table_0_row_0"
    assert ref.page == 41
    assert ref.document_id == doc.document_id
    assert doc.refs[ref.ref_id] is ref


def test_extract_pdf_skips_tables_on_narrative_only_pages():
    data = _load("golden_indian.pdf")
    doc = extract_pdf(data, validate_input(data))
    pages_with_tables = {t.first_page for t in doc.tables}
    # 39 leading filler pages carry prose only; none should cost a table pass.
    assert not any(2 <= p <= 40 for p in pages_with_tables)


def test_continuation_table_without_header_is_recorded_with_empty_header():
    data = _load("stitched.pdf")
    doc = extract_pdf(data, validate_input(data))
    by_page = {t.first_page: t for t in doc.tables}
    assert by_page[5].header == ("Particulars", "As at 31 March 2024", "As at 31 March 2023")
    assert by_page[6].header == ()
    assert by_page[6].rows[0].label == "Other current assets"
    assert by_page[6].rows[0].ref.page == 6


def test_hostile_pdf_extracts_without_crashing_and_keeps_raw_tokens():
    data = _load("hostile.pdf")
    doc = extract_pdf(data, validate_input(data))
    by_page = {t.first_page: t for t in doc.tables}
    income = by_page[3]
    labels = [r.label for r in income.rows]
    assert "Revenue from operations" in labels
    cogs = next(r for r in income.rows if r.label == "Cost of materials consumed")
    assert cogs.cells[1] == "\u2014"
    assert cogs.cells[2] == ""
