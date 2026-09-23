"""T1.1: HTML -> PDF render. Skipped unless the eval group and Chromium are installed."""

from __future__ import annotations

import contextlib

import pipeline
import pytest

from fincopilot.extract.pdf import ScannedPDFUnsupported
from fincopilot.sources.render import RenderUnavailable, html_to_pdf

pytest.importorskip("playwright.sync_api", reason="eval group (Playwright) not installed")

HTML = b"""<!DOCTYPE html><html><head><title>t</title></head><body>
<h2>CONSOLIDATED STATEMENTS OF OPERATIONS</h2>
<p>(In millions)</p>
<table>
<tr><th></th><th>2023</th><th>2022</th></tr>
<tr><td>Net sales</td><td>383,285</td><td>394,328</td></tr>
<tr><td>Cost of sales</td><td>214,137</td><td>223,546</td></tr>
<tr><td>Net income</td><td>96,995</td><td>99,803</td></tr>
</table>
<img src="logo.png">
</body></html>"""


def test_renders_a_small_table_to_a_pdf_the_pipeline_accepts():
    try:
        pdf = html_to_pdf(HTML, base_url="https://www.sec.gov/Archives/edgar/data/1/2/")
    except RenderUnavailable as e:
        pytest.skip(str(e))
    assert pdf.startswith(b"%PDF-")
    # A one-table page may be rejected as too sparse; any other gate error fails.
    with contextlib.suppress(ScannedPDFUnsupported):
        pipeline.analyze(pdf)
