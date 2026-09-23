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


def truth_for_filing(facts: dict, accession: str) -> tuple[list[TruthValue], list[str]]:
    """Truth values for one filing and a note for every exclusion.

    The year of a fact is the year of its `end` date, never `fy`: `fy` is the
    filing's fiscal year, so prior-year comparatives carry the same `fy`.
    """
    gaap = facts.get("facts", {}).get("us-gaap", {})
    truth: list[TruthValue] = []
    notes: list[str] = []
    for concept, spec in CONCEPT_TAGS.items():
        # year -> tag -> distinct values (Decimal keys dedupe "100" and "100.0")
        by_year: dict[int, dict[str, dict[Decimal, str]]] = {}
        for tag in spec.tags:
            usd = gaap.get(tag, {}).get("units", {}).get("USD", [])
            in_filing = [f for f in usd if f["accn"] == accession]
            kept = [f for f in in_filing if _kind_ok(f, spec.kind)]
            if dropped := len(in_filing) - len(kept):
                notes.append(
                    f"{concept.value}/{tag}: dropped {dropped} fact(s) that are not "
                    f"{'an instant' if spec.kind == 'instant' else 'a 350-380 day duration'}"
                )
            for f in kept:
                text = str(f["val"])
                year_tags = by_year.setdefault(date.fromisoformat(f["end"]).year, {})
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
