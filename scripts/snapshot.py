"""Regression snapshot: everything the pipeline decides, AI off, one fact per line.

Owns the canonical text form of an AnalysisResult and the committed snapshot of
the synthetic fixtures. Never changes pipeline behaviour, never calls a model,
never writes `document_id` (a random UUID per run) and never converts a Decimal
to float.

    uv run python scripts/snapshot.py --check    # default; exit 1 on any diff
    uv run python scripts/snapshot.py --update   # rewrite the snapshot files
"""

from __future__ import annotations

import argparse
import difflib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipeline

from fincopilot.extract.pdf import IngestionError
from fincopilot.types import (
    AnalysisResult,
    CanonicalConcept,
    FinancialValue,
    Statement,
    Unavailable,
)

ROOT = Path(__file__).resolve().parents[1]
TARGETS: tuple[tuple[Path, Path], ...] = (
    (ROOT / "tests" / "fixtures", ROOT / "tests" / "snapshots" / "fixtures.snap"),
    (ROOT / "tests" / "fixtures" / "real", ROOT / ".snapshots" / "real.snap"),
)
_CONCEPTS = frozenset(c.value for c in CanonicalConcept)


def _why(u: Unavailable) -> str:
    root = u.root()
    return f"{root.reason.value}: {root.detail}"


def _source(v: FinancialValue) -> str:
    if v.cell is not None:
        return v.cell.ref.ref_id
    return "derived:" + "+".join(v.derived_from or ())


def _result_lines(name: str, r: AnalysisResult) -> list[str]:
    facts: list[tuple[str, str, str]] = [("basis", "-", r.statements.basis.value)]
    for kind in ("income", "balance", "cash_flow"):
        stmt = getattr(r.statements, kind)
        facts.append(
            (
                "statement",
                kind,
                f"{stmt.table.table_id} pages={stmt.table.pages}"
                if isinstance(stmt, Statement)
                else f"UNAVAILABLE {_why(stmt)}",
            )
        )
    facts.append(
        (
            "periods",
            "-",
            f"UNAVAILABLE {_why(r.periods)}"
            if isinstance(r.periods, Unavailable)
            else ",".join(str(p.end_year) for p in r.periods.ordered),
        )
    )
    for v in r.values:
        facts.append(
            (
                "value",
                f"{v.concept.value}@{v.period.end_year}",
                f"{v.value} {v.currency} src={_source(v)} "
                f"conf={v.extraction_confidence.value}/{v.analytical_confidence.value}",
            )
        )
    for (key, period), why in r.metric_set.unavailable.items():
        kind = "value_unavailable" if key in _CONCEPTS else "metric_unavailable"
        facts.append((kind, f"{key}@{period.end_year}", _why(why)))
    for m in r.metrics:
        facts.append(
            (
                "metric",
                f"{m.name}@{m.period.end_year}",
                f"{m.value} {m.unit.value} conf={m.analytical_confidence.value}",
            )
        )
    for t in r.trends:
        rel = "UNAVAILABLE" if isinstance(t.relative_change, Unavailable) else t.relative_change
        facts.append(
            (
                "trend",
                f"{t.subject}@{t.from_period.end_year}->{t.to_period.end_year}",
                f"{t.absolute_change} rel={rel} {t.direction.value} {t.economic.value}",
            )
        )
    for c in r.reconciliations:
        delta = "UNAVAILABLE" if isinstance(c.delta, Unavailable) else c.delta
        facts.append(("recon", f"{c.name}@{c.period.end_year}", f"{c.status.value} delta={delta}"))
    for n in r.mapping.notes:
        facts.append(
            (
                "note",
                n.concept.value,
                f"kept={n.kept_ref} dropped={n.dropped_ref} reason={n.reason}",
            )
        )
    for f in r.red_flags:
        facts.append(("flag", f.rule_id, f"{f.outcome.value} {f.severity.value}"))
    return [_line(name, *fact) for fact in facts]


def _line(name: str, kind: str, key: str, payload: str) -> str:
    # One fact per line: an embedded newline (e.g. in a detail string) must not split it.
    return f"{name} | {kind} | {key} | {payload}".replace("\n", "\\n")


def snapshot_lines(name: str, data: bytes) -> list[str]:
    """Every fact the pipeline decides about one PDF, AI off, sorted."""
    try:
        result = pipeline.analyze(data)
    except IngestionError as exc:
        return [_line(name, "error", "-", f"{type(exc).__name__}: {exc}")]
    return sorted(_result_lines(name, result))


def build(pdf_dir: Path) -> list[str]:
    """Snapshot lines for every PDF directly in `pdf_dir`, sorted."""
    lines: list[str] = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        lines.extend(snapshot_lines(pdf.name, pdf.read_bytes()))
    return sorted(lines)


def diff(expected: list[str], actual: list[str], label: str = "snapshot") -> list[str]:
    """Unified diff lines; empty when the two snapshots agree."""
    return list(
        difflib.unified_diff(
            expected, actual, f"{label} (committed)", f"{label} (now)", lineterm=""
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="compare with the snapshot (default)")
    mode.add_argument("--update", action="store_true", help="rewrite the snapshot files")
    args = parser.parse_args(argv)

    status = 0
    for pdf_dir, snap in TARGETS:
        if not any(pdf_dir.glob("*.pdf")):
            continue
        lines = build(pdf_dir)
        label = snap.relative_to(ROOT).as_posix()
        if args.update:
            snap.parent.mkdir(parents=True, exist_ok=True)
            snap.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            print(f"wrote {label} ({len(lines)} lines)")
            continue
        if not snap.exists():
            print(f"{label}: no snapshot, run --update")
            status = 2
            continue
        changes = diff(snap.read_text(encoding="utf-8").splitlines(), lines, label)
        if changes:
            print("\n".join(changes))
            status = max(status, 1)
        else:
            print(f"{label}: ok ({len(lines)} lines)")
    return status


if __name__ == "__main__":
    sys.exit(main())
