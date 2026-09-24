"""HTML -> PDF with headless Chromium (Playwright). Used by the eval harness only.

Owns: turning an EDGAR HTML filing into PDF bytes the app can read. Playwright
is an optional eval-only dependency, so it is imported inside the function.

It must never fetch anything: the page is loaded from a temp file and every
non-file request is aborted, so a render is offline and repeatable, and
untrusted filing HTML cannot make the browser call out. Caching rendered PDFs
is the caller's job.
"""

from __future__ import annotations

import html as html_lib
import re
import tempfile
from pathlib import Path

INSTALL_HINT = "uv sync --dev --group eval && uv run playwright install chromium"

_HEAD = re.compile(rb"<head[^>]*>", re.IGNORECASE)
_TIMEOUT_MS = 180_000


class RenderUnavailable(Exception):
    """Playwright or its Chromium build is not installed."""


def html_to_pdf(html: bytes, *, base_url: str) -> bytes:
    """Render `html` to a Letter PDF. Relative links resolve against `base_url`."""
    try:
        from playwright.sync_api import Error, sync_playwright
    except ImportError as e:
        raise RenderUnavailable(f"Playwright is not installed. Run: {INSTALL_HINT}") from e

    base = f'<base href="{html_lib.escape(base_url, quote=True)}">'.encode()
    match = _HEAD.search(html)
    if match:
        html = html[: match.end()] + base + html[match.end() :]

    with tempfile.TemporaryDirectory() as tmp:
        page_path = Path(tmp) / "filing.html"
        page_path.write_bytes(html)
        with sync_playwright() as pw:
            try:
                browser = pw.chromium.launch()
            except Error as e:
                raise RenderUnavailable(f"Chromium is not installed. Run: {INSTALL_HINT}") from e
            try:
                page = browser.new_page()
                page.route(
                    "**/*",
                    lambda route: (
                        route.continue_()
                        if route.request.url.startswith("file:")
                        else route.abort()
                    ),
                )
                page.goto(page_path.as_uri(), wait_until="load", timeout=_TIMEOUT_MS)
                return page.pdf(format="Letter", print_background=False)
            finally:
                browser.close()
