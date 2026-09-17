"""Ingestion gate and raw extraction. Spec section 4.1 and 4.2.

This is the ONLY module that performs PDF I/O, and the only place a
SourceRef is minted. Everything downstream is a pure function of the
RawDocument returned here.
"""

from __future__ import annotations

import io
import re
import uuid
from dataclasses import dataclass

import pdfplumber

from fincopilot.extract.anchors import (
    candidate_table_pages,
    find_anchors,
    is_amount_token,
    looks_like_header,
)
from fincopilot.extract.textgrid import Word, text_grid
from fincopilot.types import ExtractedTable, RawDocument, SourceRef, TableRow, make_ref_id

DEFAULT_MAX_BYTES = 50 * 1024 * 1024
DEFAULT_MAX_PAGES = 1000

_PDF_MAGIC = b"%PDF-"
_WORD = re.compile(r"[A-Za-z]{2,}")


class IngestionError(Exception):
    """Base for every gate rejection. Messages never echo document content."""


class FileTooLarge(IngestionError):
    pass


class NotAPDF(IngestionError):
    pass


class UnreadablePDF(IngestionError):
    pass


class TooManyPages(IngestionError):
    pass


class ScannedPDFUnsupported(IngestionError):
    pass


@dataclass(frozen=True, slots=True)
class DocumentRef:
    """Opaque handle. The document_id is a UUID, never a user-supplied name."""

    document_id: str
    size_bytes: int


def validate_input(data: bytes, *, max_bytes: int = DEFAULT_MAX_BYTES) -> DocumentRef:
    """Cheapest rejections first: size, then magic bytes. Nothing is parsed."""
    if len(data) > max_bytes:
        raise FileTooLarge(f"upload is {len(data)} bytes; limit is {max_bytes}")
    if not data.startswith(_PDF_MAGIC):
        raise NotAPDF("file does not begin with %PDF-")
    return DocumentRef(document_id=uuid.uuid4().hex, size_bytes=len(data))


def _probe_text_layer(page_texts: list[str]) -> None:
    """Heuristic, multi-signal. Raises ScannedPDFUnsupported.

    Signals: total characters, distribution across sampled pages, and whether
    the characters form words rather than isolated glyphs. A document where a
    handful of pages carry all the text and the rest carry none is treated as
    image-only with an OCR cover page, not as text-bearing.
    """
    n = len(page_texts)
    if n == 0:
        # A truncated download can parse as a valid PDF with no pages at all.
        # Nothing downstream can work from that, so it is refused at the gate.
        raise UnreadablePDF("PDF contains no pages")
    sample_idx = sorted({round(i * (n - 1) / 11) for i in range(12)}) if n > 1 else [0]
    sampled = [page_texts[i] for i in sample_idx]

    total_chars = sum(len(t) for t in sampled)
    pages_with_words = sum(1 for t in sampled if len(_WORD.findall(t)) >= 10)
    if total_chars < 200:
        raise ScannedPDFUnsupported("no usable text layer: fewer than 200 characters sampled")
    if pages_with_words / len(sampled) < 0.3:
        raise ScannedPDFUnsupported(
            "sparse text layer: fewer than 30% of sampled pages contain readable words"
        )


_YEAR_RE = re.compile(r"(?<![0-9])(?:19|20|21)[0-9]{2}(?![0-9])")
DEFAULT_X_TOLERANCE = 3.0
TIGHT_X_TOLERANCE = 1.5
Y_TOLERANCE = 1.5  # points; pdfplumber's default of 3.0 merges adjacent rows
MIN_SPACE_RATIO = 0.08  # ordinary prose is ~0.12-0.18 spaces per character


def _space_ratio(page_texts: list[str]) -> float:
    total = sum(len(t) for t in page_texts)
    return sum(t.count(" ") for t in page_texts) / total if total else 1.0


def _usable(t: ExtractedTable) -> bool:
    """Two period-bearing header cells, two mostly-numeric columns, three rows.

    Anything less and the word-position grid is built as well; location
    scoring then picks whichever reads better."""
    if len(t.rows) < 3 or sum(1 for c in t.header if _YEAR_RE.search(c)) < 2:
        return False
    width = max(len(r.cells) for r in t.rows)
    numeric = 0
    for col in range(1, width):
        cells = [r.cells[col] for r in t.rows if col < len(r.cells) and r.cells[col]]
        if cells and sum(1 for c in cells if is_amount_token(c)) * 2 > len(cells):
            numeric += 1
    return numeric >= 2


def _clean(cell: str | None) -> str:
    return " ".join((cell or "").split())


def _caption(page_text: str, header: tuple[str, ...], body: list[list[str]]) -> str | None:
    """Text printed directly above the table, minus any statement heading.

    pdfplumber attaches no caption to a table; the scale phrase sits in the
    page text between the heading and the first table line.
    """
    target = " ".join(c for c in header if c) if header else (body[0][0] if body else "")
    if not target:
        return None
    lines = page_text.splitlines()
    idx = next((i for i, line in enumerate(lines) if line.startswith(target[:24])), None)
    if idx is None:
        return None
    above = [line for line in lines[max(0, idx - 2) : idx] if not find_anchors(line)]
    return " ".join(above).strip() or None


def _build_table(
    document_id: str,
    page_no: int,
    page_text: str,
    table_idx: int,
    rows: list[list[str | None]],
    col_x: tuple[float, ...],
) -> ExtractedTable | None:
    cleaned = [[_clean(c) for c in r] for r in rows if r and any(_clean(c) for c in r)]
    if not cleaned:
        return None
    header: tuple[str, ...] = ()
    body = cleaned
    if looks_like_header(cleaned[0]):
        header = tuple(cleaned[0])
        body = cleaned[1:]
    caption = _caption(page_text, header, body)
    table_rows = []
    for row_idx, cells in enumerate(body):
        label = cells[0]
        ref = SourceRef(
            ref_id=make_ref_id(page_no, table_idx, row_idx),
            document_id=document_id,
            page=page_no,
            table_idx=table_idx,
            row_idx=row_idx,
            col_idx=None,
            row_label=label,
            raw_text=" | ".join(cells),
        )
        table_rows.append(TableRow(ref=ref, label=label, cells=tuple(cells)))
    return ExtractedTable(
        table_id=f"page_{page_no}_table_{table_idx}",
        first_page=page_no,
        pages=(page_no,),
        header=header,
        rows=tuple(table_rows),
        caption=caption,
        col_x=col_x,
    )


def _page_texts(pdf: pdfplumber.PDF, page_count: int, x_tol: float) -> list[str]:
    """Text for every page, releasing each page as soon as it is read.

    pdfplumber keeps every char, line and rect it parsed on the Page object for
    the lifetime of the PDF. Over a 481-page annual report that is hundreds of
    megabytes held for text already copied out, which is enough to get the
    process killed outright on a small container -- no traceback, just a dead
    app. close() drops the cache; the page re-parses if asked again.
    """
    texts = []
    for i in range(page_count):
        page = pdf.pages[i]
        texts.append(page.extract_text(x_tolerance=x_tol) or "")
        page.close()
    return texts


def extract_pdf(
    data: bytes, ref: DocumentRef, *, max_pages: int = DEFAULT_MAX_PAGES
) -> RawDocument:
    """Open, gate, and extract. Tables are pulled only from candidate pages.

    Gate order after validate_input: open (corrupt/encrypted), page cap,
    text-layer probe. Then text for every page, then tables on the pages the
    text pass flagged as statement anchors or numeric-dense.
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as exc:  # pdfminer raises many types for bad input
        raise UnreadablePDF("could not open PDF") from exc

    with pdf:
        page_count = len(pdf.pages)
        if page_count > max_pages:
            raise TooManyPages(f"{page_count} pages; limit is {max_pages}")

        x_tol = DEFAULT_X_TOLERANCE
        page_texts = _page_texts(pdf, page_count, x_tol)
        if _space_ratio(page_texts) < MIN_SPACE_RATIO:
            # Some fonts (Berkshire's 10-K, for one) pack glyphs so tightly that
            # pdfplumber's default tolerance swallows every space. Re-read once,
            # document-wide, with a tighter tolerance. Deterministic.
            x_tol = TIGHT_X_TOLERANCE
            page_texts = _page_texts(pdf, page_count, x_tol)
        _probe_text_layer(page_texts)

        tables: list[ExtractedTable] = []
        for page_no in candidate_table_pages(page_texts):
            page = pdf.pages[page_no - 1]
            for table_idx, found in enumerate(page.find_tables()):
                col_x = (
                    tuple(round(c[0], 1) for c in found.rows[0].cells if c) if found.rows else ()
                )
                built = _build_table(
                    ref.document_id,
                    page_no,
                    page_texts[page_no - 1],
                    table_idx,
                    found.extract(x_tolerance=x_tol, y_tolerance=Y_TOLERANCE),
                    col_x,
                )
                if built is not None:
                    tables.append(built)
            if not any(_usable(t) for t in tables if t.first_page == page_no):
                # No ruled table worth reading: rebuild the grid from word positions.
                words = [
                    Word(w["text"], float(w["x0"]), float(w["x1"]), float(w["top"]))
                    # A statement printed with tight leading puts two rows inside
                    # pdfplumber's default 3.0pt line tolerance. The rows then merge
                    # into one cluster, sort by x0, and a neighbour's glyph lands in
                    # the middle of a number: '245,122' comes out as '245,' + '122'.
                    # The fragment is not a valid amount, so the whole row collapses
                    # into its label and every figure on it is lost. text_grid does
                    # its own line assembly, so reading words row-tight costs nothing.
                    for w in page.extract_words(x_tolerance=x_tol, y_tolerance=Y_TOLERANCE)
                ]
                grid = text_grid(words)
                if grid is not None:
                    rows, col_x = grid
                    n = sum(1 for t in tables if t.first_page == page_no)
                    built = _build_table(
                        ref.document_id, page_no, page_texts[page_no - 1], n, rows, col_x
                    )
                    if built is not None:
                        tables.append(built)
            # find_tables and extract_words repopulate the same cache _page_texts
            # frees, so a long run of candidate pages rebuilds it page by page.
            page.close()

    refs = {row.ref.ref_id: row.ref for t in tables for row in t.rows}
    return RawDocument(
        document_id=ref.document_id,
        page_count=page_count,
        page_text=tuple(page_texts),
        tables=tuple(tables),
        refs=refs,
    )
