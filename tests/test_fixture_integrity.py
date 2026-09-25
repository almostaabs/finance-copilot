"""Fixtures are committed artifacts. This test proves they have not moved.

A failure means either a fixture was regenerated without updating hashes.json,
or a PDF was corrupted. Both invalidate every golden assertion downstream.
"""

import hashlib
import json
from pathlib import Path

import pdfplumber
import pytest

FIXTURE_DIR = Path(__file__).parent / "fixtures"
EXPECTED_DIR = FIXTURE_DIR / "expected"

EXPECTED_FIXTURES = {
    "golden_indian.pdf",
    "golden_us.pdf",
    "stitched.pdf",
    "standalone_only.pdf",
    "ambiguous_periods.pdf",
    "no_scale.pdf",
    "scanned.pdf",
    "hostile.pdf",
    "text_aligned.pdf",
    "footnote_table.pdf",
    "component_total.pdf",
    "percent_sales.pdf",
    "unprefixed_10k.pdf",
}


def test_every_pinned_fixture_is_present():
    found = {p.name for p in FIXTURE_DIR.glob("*.pdf")}
    assert found == EXPECTED_FIXTURES


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_fixture_bytes_match_the_pinned_hash(name):
    pinned = json.loads((EXPECTED_DIR / "hashes.json").read_text(encoding="utf-8"))
    actual = hashlib.sha256((FIXTURE_DIR / name).read_bytes()).hexdigest()
    assert actual == pinned[name], (
        f"{name} does not match its pinned hash. If this was a deliberate "
        f"fixture change, regenerate and re-pin in the SAME commit."
    )


@pytest.mark.parametrize("name", sorted(EXPECTED_FIXTURES))
def test_every_fixture_opens(name):
    with pdfplumber.open(FIXTURE_DIR / name) as pdf:
        assert len(pdf.pages) > 0


def test_expected_value_files_are_valid_json():
    for path in EXPECTED_DIR.glob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))


def test_expected_values_only_name_real_canonical_concepts():
    from fincopilot.types import CanonicalConcept

    valid = {c.value for c in CanonicalConcept}
    for name in ("golden_indian.json", "golden_us.json"):
        expected = json.loads((EXPECTED_DIR / name).read_text(encoding="utf-8"))
        named = (
            set(expected["mapped"]) | set(expected["derived"]) | set(expected.get("unmapped", []))
        )
        assert named <= valid, f"{name} names unknown concepts: {named - valid}"


def test_golden_us_covers_the_concepts_golden_indian_cannot():
    expected = json.loads((EXPECTED_DIR / "golden_us.json").read_text(encoding="utf-8"))
    # gross_profit has no Ind-AS line, so golden_us is the only fixture that
    # exercises gross_margin end to end.
    assert "gross_profit" in expected["mapped"]
    assert "ebitda" in expected["derived"]
    assert expected["periods_by_statement"]["income"] != expected["periods_by_statement"]["balance"]
