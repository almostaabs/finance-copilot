"""scripts/snapshot.py: matches the committed file, never leaks run IDs, catches a change."""

from __future__ import annotations

import re
from pathlib import Path

import pipeline
from scripts.snapshot import build, diff, snapshot_lines

FIXTURES = Path(__file__).parent / "fixtures"
SNAPSHOT = Path(__file__).parent / "snapshots" / "fixtures.snap"

# 32 hex chars, word-bounded, with at least one letter: a UUID hex, not a long decimal.
DOCUMENT_ID_PATTERN = re.compile(r"\b(?=[0-9a-f]*[a-f])[0-9a-f]{32}\b")


def _committed() -> list[str]:
    return SNAPSHOT.read_text(encoding="utf-8").splitlines()


def test_fixture_snapshot_matches() -> None:
    changes = diff(_committed(), build(FIXTURES), "tests/snapshots/fixtures.snap")
    assert not changes, (
        "Pipeline output differs from the committed snapshot. "
        "Run `uv run python scripts/snapshot.py --check` for the diff."
    )


def test_snapshot_never_contains_document_id() -> None:
    lines: list[str] = []
    ids: list[str] = []
    for pdf in sorted(FIXTURES.glob("*.pdf")):
        data = pdf.read_bytes()
        lines.extend(snapshot_lines(pdf.name, data))
        if pdf.name != "scanned.pdf":  # rejected at the gate: no result, no id
            ids.append(pipeline.analyze(data).document_id)
    assert ids
    for doc_id in ids:
        assert not any(doc_id in line for line in lines), doc_id
    assert not [line for line in lines + _committed() if DOCUMENT_ID_PATTERN.search(line)]


def test_snapshot_detects_a_changed_value() -> None:
    lines = snapshot_lines("golden_us.pdf", (FIXTURES / "golden_us.pdf").read_bytes())
    i = next(i for i, line in enumerate(lines) if " | value | net_income@2024 | " in line)
    perturbed = [*lines]
    perturbed[i] = perturbed[i].replace("643000000", "643000001", 1)
    assert perturbed != lines
    assert not diff(lines, lines)
    changes = diff(lines, perturbed)
    assert any(c.startswith("-") and "643000000" in c for c in changes)
    assert any(c.startswith("+") and "643000001" in c for c in changes)
