"""Deterministic fixture generator.

Run by hand when a fixture DATA changes:

    uv run python -m tests.fixtures.build_fixtures

Then commit the regenerated PDFs AND the updated hashes.json in the same
commit. Tests never call main() -- the PDFs are committed artifacts, and a
fixture that regenerates differently under a new ReportLab silently
invalidates every golden assertion.

This module must never import from fincopilot. It is the independent ground
truth; importing the code under test would make it circular.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from reportlab import rl_config

# Must be set before the platypus imports below snapshot the config. Suppresses
# timestamps and document IDs, making output byte-identical across runs.
rl_config.invariant = 1

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet  # noqa: E402
from reportlab.lib.units import mm  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

FIXTURE_DIR = Path(__file__).parent

_FILLER = (
    "The Board of Directors presents the annual report together with the audited "
    "financial statements for the year under review. The Company continued to focus "
    "on operational efficiency, disciplined capital allocation, and long-term value "
    "creation across its business segments during the period."
)


@dataclass(frozen=True)
class StatementBlock:
    """One statement, rendered starting on its own page."""

    heading: str
    caption: str | None
    header: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    split_after_row: int | None = None  # force a page break mid-table
    repeat_header_on_split: bool = False
    grid: bool = True  # False produces an unruled table


@dataclass(frozen=True)
class ReportSpec:
    title: str
    subtitle: str
    blocks: tuple[StatementBlock, ...]
    leading_filler_pages: int = 0
    trailing_filler_pages: int = 0
    between_filler_pages: int = 0
    document_note: str | None = None  # e.g. a document-level scale statement
    injection_text: str | None = None  # hostile fixture only
    metadata_title: str = "Annual Report"


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=16, spaceAfter=8),
        "heading": ParagraphStyle("h", parent=base["Heading2"], fontSize=12, spaceAfter=6),
        "caption": ParagraphStyle("c", parent=base["Normal"], fontSize=8, spaceAfter=6),
        "body": ParagraphStyle("b", parent=base["Normal"], fontSize=9, leading=13),
    }


def _table_style(grid: bool) -> TableStyle:
    commands = [
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "LEFT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    if grid:
        # Ruled lines are what the pdfplumber lattice strategy detects.
        commands.append(("GRID", (0, 0), (-1, -1), 0.5, colors.black))
    return TableStyle(commands)


def _col_widths(header: tuple[str, ...]) -> list[float]:
    label_width = 75 * mm
    remaining = 180 * mm - label_width
    value_width = remaining / max(1, len(header) - 1)
    return [label_width] + [value_width] * (len(header) - 1)


def _filler_pages(count: int, styles: dict[str, ParagraphStyle]) -> list:
    story: list = []
    for _ in range(count):
        story.append(Paragraph(_FILLER, styles["body"]))
        story.append(Spacer(1, 6 * mm))
        story.append(Paragraph(_FILLER, styles["body"]))
        story.append(PageBreak())
    return story


def _render_block(block: StatementBlock, styles: dict[str, ParagraphStyle]) -> list:
    story: list = [Paragraph(block.heading, styles["heading"])]
    if block.caption:
        story.append(Paragraph(block.caption, styles["caption"]))

    widths = _col_widths(block.header)
    style = _table_style(block.grid)

    if block.split_after_row is None:
        data = [list(block.header)] + [list(r) for r in block.rows]
        story.append(Table(data, colWidths=widths, style=style))
        return story

    head = [list(block.header)] + [list(r) for r in block.rows[: block.split_after_row]]
    story.append(Table(head, colWidths=widths, style=style))
    story.append(PageBreak())

    tail_rows = [list(r) for r in block.rows[block.split_after_row :]]
    tail = ([list(block.header)] if block.repeat_header_on_split else []) + tail_rows
    story.append(Table(tail, colWidths=widths, style=style))
    return story


def build_report(spec: ReportSpec, out_path: Path) -> None:
    """Render one fixture PDF. Deterministic for a given spec."""
    styles = _styles()
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
        title=spec.metadata_title,
        author="Fixture Generator",
        subject="Test fixture",
        creator="fincopilot-fixtures",
    )

    story: list = [
        Paragraph(spec.title, styles["title"]),
        Paragraph(spec.subtitle, styles["body"]),
    ]
    if spec.document_note:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(spec.document_note, styles["caption"]))
    if spec.injection_text:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph(spec.injection_text, styles["body"]))
    story.append(PageBreak())

    story.extend(_filler_pages(spec.leading_filler_pages, styles))

    for index, block in enumerate(spec.blocks):
        story.extend(_render_block(block, styles))
        if index != len(spec.blocks) - 1:
            story.append(PageBreak())
            story.extend(_filler_pages(spec.between_filler_pages, styles))

    if spec.trailing_filler_pages:
        story.append(PageBreak())
        story.extend(_filler_pages(spec.trailing_filler_pages, styles))

    doc.build(story)


def build_scanned_pdf(out_path: Path) -> None:
    """A PDF with NO text layer: drawn shapes only.

    Produces the ScannedPDFUnsupported case. Nothing here emits a text object,
    so page.extract_text() returns an empty string on every page.
    """
    from reportlab.pdfgen import canvas as pdfcanvas

    c = pdfcanvas.Canvas(str(out_path), pagesize=A4, invariant=1)
    _, height = A4

    for page in range(3):
        # Grey bars that LOOK like scanned text but carry no text objects.
        y = height - 40 * mm
        for row in range(28):
            bar_width = (120 + (row * 37) % 260) * 0.5 * mm
            c.setFillGray(0.55 + ((row + page) % 3) * 0.1)
            c.rect(20 * mm, y, bar_width, 2.4 * mm, stroke=0, fill=1)
            y -= 6 * mm
        c.showPage()

    c.save()


def write_hashes() -> None:
    """Pin every committed fixture SHA-256.

    Run ONLY after a deliberate fixture change, in the same commit as the
    regenerated PDFs. If this runs by accident, the golden ground truth moves
    without anyone noticing -- the exact failure the pin exists to stop.
    """
    import hashlib
    import json

    digests = {}
    for pdf in sorted(FIXTURE_DIR.glob("*.pdf")):
        digests[pdf.name] = hashlib.sha256(pdf.read_bytes()).hexdigest()

    target = FIXTURE_DIR / "expected" / "hashes.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(digests, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target}")


def main() -> None:
    """Regenerate every committed fixture PDF. Run by hand, never from a test."""
    from tests.fixtures.data.edge_cases import (
        AMBIGUOUS_PERIODS,
        HOSTILE,
        NO_SCALE,
        STANDALONE_ONLY,
        STITCHED,
    )
    from tests.fixtures.data.golden_indian import GOLDEN_INDIAN
    from tests.fixtures.data.golden_us import GOLDEN_US

    targets = {
        "golden_indian.pdf": GOLDEN_INDIAN,
        "golden_us.pdf": GOLDEN_US,
        "stitched.pdf": STITCHED,
        "standalone_only.pdf": STANDALONE_ONLY,
        "ambiguous_periods.pdf": AMBIGUOUS_PERIODS,
        "no_scale.pdf": NO_SCALE,
        "hostile.pdf": HOSTILE,
    }
    for name, spec in targets.items():
        out = FIXTURE_DIR / name
        build_report(spec, out)
        print(f"wrote {out}")

    scanned = FIXTURE_DIR / "scanned.pdf"
    build_scanned_pdf(scanned)
    print(f"wrote {scanned}")

    write_hashes()


if __name__ == "__main__":
    main()
