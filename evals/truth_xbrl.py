"""Ground truth for one filing from SEC companyfacts JSON.

Owns the rules that turn companyfacts into (concept, end year) truth values,
and the frozen truth files under `evals/truth/`. Pure logic plus one file
write; never fetches, and never picks between two conflicting values: a
conflict is excluded with a note.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from evals.concept_tags import CONCEPT_TAGS

MIN_ANNUAL_DAYS, MAX_ANNUAL_DAYS = 350, 380


@dataclass(frozen=True, slots=True)
class TruthValue:
    concept: str  # CanonicalConcept.value
    end_year: int
    values: tuple[str, ...]  # accepted Decimal strings, one per matching tag, deduplicated
    tags: tuple[str, ...]


def _kind_ok(fact: dict, kind: str) -> bool:
    if kind == "instant":
        return "start" not in fact
    if "start" not in fact:
        return False
    days = (date.fromisoformat(fact["end"]) - date.fromisoformat(fact["start"])).days
    return MIN_ANNUAL_DAYS <= days <= MAX_ANNUAL_DAYS


def _year_offset(gaap: dict, accession: str, latest_end: date) -> tuple[int | None, str | None]:
    """How this filing names its fiscal year: fy - year(latest period end).

    HD calls the year ending 2026-02-01 "fiscal 2025" (offset -1); NVDA calls the
    year ending 2026-01-25 "fiscal 2026" (offset 0). Returns (offset, None), or
    (None, why) when fy is inconsistent or the offset is not 0 or -1.
    """
    fys = {
        f.get("fy")
        for tag in gaap.values()
        for facts in tag.get("units", {}).values()
        for f in facts
        if f.get("accn") == accession
    }
    if len(fys) != 1 or not isinstance(next(iter(fys)), int):
        return None, f"fy is inconsistent across the filing's facts: {sorted(map(str, fys))}"
    offset = next(iter(fys)) - latest_end.year
    if offset not in (0, -1):
        return None, f"fiscal-year offset {offset} (fy - year of {latest_end}) is not 0 or -1"
    return offset, None


def truth_for_filing(facts: dict, accession: str) -> tuple[list[TruthValue], list[str]]:
    """Truth values for one filing and a note for every exclusion.

    The year of a fact is the year of its `end` date plus the filing's own
    fiscal-year offset (see `_year_offset`), so a truth year is the year the
    filing prints over the column. `fy` alone is never the year: comparatives
    carry the filing's `fy`. The latest end is taken over the facts this module
    scores (the right kind, this accession), not every fact: a filing may carry a
    fact dated after its year end.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    notes: list[str] = []
    kept_by_concept: dict = {}
    for concept, spec in CONCEPT_TAGS.items():
        for tag in spec.tags:
            usd = gaap.get(tag, {}).get("units", {}).get("USD", [])
            in_filing = [f for f in usd if f["accn"] == accession]
            kept = [f for f in in_filing if _kind_ok(f, spec.kind)]
            if dropped := len(in_filing) - len(kept):
                notes.append(
                    f"{concept.value}/{tag}: dropped {dropped} fact(s) that are not "
                    f"{'an instant' if spec.kind == 'instant' else 'a 350-380 day duration'}"
                )
            kept_by_concept.setdefault(concept, []).append((tag, kept))

    ends = [date.fromisoformat(f["end"]) for c in kept_by_concept.values() for _, k in c for f in k]
    if not ends:
        return [], notes
    offset, why = _year_offset(gaap, accession, max(ends))
    if offset is None:
        return [], [*notes, f"whole filing excluded: {why}"]
    if offset:
        notes.append(f"fiscal years named by start year: truth year = end year {offset:+d}")

    truth: list[TruthValue] = []
    for concept, tagged in kept_by_concept.items():
        # year -> tag -> distinct values (Decimal keys dedupe "100" and "100.0")
        by_year: dict[int, dict[str, dict[Decimal, str]]] = {}
        for tag, kept in tagged:
            for f in kept:
                text = str(f["val"])
                year = date.fromisoformat(f["end"]).year + offset
                year_tags = by_year.setdefault(year, {})
                year_tags.setdefault(tag, {}).setdefault(Decimal(text), str(Decimal(text)))
        for year in sorted(by_year):
            tag_values = by_year[year]
            conflicted = {t: v for t, v in tag_values.items() if len(v) > 1}
            if conflicted:
                for tag, vals in conflicted.items():
                    notes.append(
                        f"{concept.value} {year}: excluded, {tag} has conflicting values "
                        f"{sorted(vals.values())}"
                    )
                continue
            values = tuple(dict.fromkeys(v for vals in tag_values.values() for v in vals.values()))
            truth.append(TruthValue(concept.value, year, values, tuple(tag_values)))
    return truth, notes


def truth_path(truth_dir: Path, ticker: str, accession: str) -> Path:
    return truth_dir / f"{ticker}_{accession}.json"


def write_truth(
    truth_dir: Path, ticker: str, accession: str, truth: list[TruthValue], notes: list[str]
) -> Path:
    """Freeze truth to disk so later SEC amendments cannot silently move it."""
    path = truth_path(truth_dir, ticker, accession)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "ticker": ticker,
        "accession": accession,
        "truth": [asdict(t) for t in truth],
        "notes": notes,
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def read_truth(path: Path) -> tuple[list[TruthValue], list[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    truth = [
        TruthValue(t["concept"], t["end_year"], tuple(t["values"]), tuple(t["tags"]))
        for t in payload["truth"]
    ]
    return truth, payload["notes"]
