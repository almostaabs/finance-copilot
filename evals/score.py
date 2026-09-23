"""Score one analysis against its truth values.

Owns the outcome definitions (correct, wrong, withheld, unverified) and the
ratios from `docs/roadmap/tier-1-credibility/README.md`. Pure logic: reads an
`AnalysisResult`, never runs the pipeline, and never passes a truth value
back into it. Only mapped values are scored; derived values never are.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from evals.concept_tags import CONCEPT_TAGS
from evals.truth_xbrl import TruthValue
from fincopilot.types import SCALE_MULTIPLIER, AnalysisResult, CanonicalConcept, Period

OUTCOMES = ("correct", "wrong", "withheld", "unverified")
WRONG_SUBS = ("sign_mismatch", "wrong_period", "value")


@dataclass(frozen=True, slots=True)
class OutcomeRecord:
    ticker: str
    accession: str
    concept: str
    end_year: int
    outcome: str  # one of OUTCOMES
    sub: str | None  # one of WRONG_SUBS when outcome is "wrong"
    app_value: str | None
    truth_values: tuple[str, ...]
    tags: tuple[str, ...]
    ref_id: str | None
    row_label: str | None
    page: int | None
    reason: str | None  # withheld only: root Unavailable reason and detail


def _matches(app: Decimal, truth: Decimal, tol: Decimal, sign_agnostic: bool) -> bool:
    if abs(app - truth) <= tol:
        return True
    return sign_agnostic and abs(abs(app) - abs(truth)) <= tol


def score(
    result: AnalysisResult, truth: list[TruthValue], *, ticker: str, accession: str
) -> list[OutcomeRecord]:
    """One record per truth value, plus one `unverified` per mapped value without truth."""
    mapped = {(v.concept.value, v.period.end_year): v for v in result.mapping.values}
    truth_keys = {(t.concept, t.end_year) for t in truth}
    records: list[OutcomeRecord] = []

    for t in truth:
        base = {
            "ticker": ticker,
            "accession": accession,
            "concept": t.concept,
            "end_year": t.end_year,
            "truth_values": t.values,
            "tags": t.tags,
        }
        fv = mapped.get((t.concept, t.end_year))
        if fv is None:
            missing = result.metric_set.unavailable.get((t.concept, Period(t.end_year, "")))
            if missing is None:
                reason = "not_mapped"
            else:
                root = missing.root()
                reason = f"{root.reason.value}: {root.detail}"
            records.append(
                OutcomeRecord(
                    **base,
                    outcome="withheld",
                    sub=None,
                    app_value=None,
                    ref_id=None,
                    row_label=None,
                    page=None,
                    reason=reason,
                )
            )
            continue

        assert fv.cell is not None  # mapping.values holds mapped values only
        app = fv.value
        tol = SCALE_MULTIPLIER[fv.cell.scale] / 2
        agnostic = CONCEPT_TAGS[CanonicalConcept(t.concept)].sign_agnostic
        truths = [Decimal(v) for v in t.values]
        other_years = [
            Decimal(v)
            for o in truth
            if o.concept == t.concept and o.end_year != t.end_year
            for v in o.values
        ]
        if any(_matches(app, x, tol, agnostic) for x in truths):
            outcome, sub = "correct", None
        elif any(_matches(app, x, tol, True) for x in truths):
            outcome, sub = "wrong", "sign_mismatch"
        elif any(_matches(app, x, tol, agnostic) for x in other_years):
            outcome, sub = "wrong", "wrong_period"
        else:
            outcome, sub = "wrong", "value"
        records.append(
            OutcomeRecord(
                **base,
                outcome=outcome,
                sub=sub,
                app_value=str(app),
                ref_id=fv.cell.ref.ref_id,
                row_label=fv.cell.ref.row_label,
                page=fv.cell.ref.page,
                reason=None,
            )
        )

    for (concept, year), fv in sorted(mapped.items()):
        if (concept, year) in truth_keys or CanonicalConcept(concept) not in CONCEPT_TAGS:
            continue
        assert fv.cell is not None
        records.append(
            OutcomeRecord(
                ticker=ticker,
                accession=accession,
                concept=concept,
                end_year=year,
                outcome="unverified",
                sub=None,
                app_value=str(fv.value),
                truth_values=(),
                tags=(),
                ref_id=fv.cell.ref.ref_id,
                row_label=fv.cell.ref.row_label,
                page=fv.cell.ref.page,
                reason=None,
            )
        )
    return records


def _ratio(num: int, den: int) -> str:
    """Four decimal places as a string, or "n/a" when nothing was scored."""
    return str((Decimal(num) / Decimal(den)).quantize(Decimal("0.0001"))) if den else "n/a"


def totals(records: list[OutcomeRecord]) -> dict[str, int | str]:
    counts = Counter(r.outcome for r in records)
    subs = Counter(r.sub for r in records if r.outcome == "wrong")
    correct, wrong, withheld = counts["correct"], counts["wrong"], counts["withheld"]
    return {
        **{o: counts[o] for o in OUTCOMES},
        **{s: subs[s] for s in WRONG_SUBS},
        "precision": _ratio(correct, correct + wrong),
        "coverage": _ratio(correct + wrong, correct + wrong + withheld),
        "wrong_rate": _ratio(wrong, correct + wrong + withheld),
    }


def summarize(records: list[OutcomeRecord]) -> dict[str, object]:
    """Totals overall, per concept, and per filing (`<TICKER>_<accession>`)."""
    by_concept: dict[str, list[OutcomeRecord]] = {}
    by_filing: dict[str, list[OutcomeRecord]] = {}
    for r in records:
        by_concept.setdefault(r.concept, []).append(r)
        by_filing.setdefault(f"{r.ticker}_{r.accession}", []).append(r)
    return {
        "totals": totals(records),
        "per_concept": {k: totals(v) for k, v in sorted(by_concept.items())},
        "per_filing": {k: totals(v) for k, v in sorted(by_filing.items())},
    }
