"""Run an analysis and print it. Not part of the library: a way to see output.

uv run python demo.py                          # golden_us fixture
uv run python demo.py path/to/report.pdf
"""

import sys
from pathlib import Path

import pipeline

from fincopilot.types import is_unavailable

DEFAULT_PDF = Path("tests/fixtures/golden_us.pdf")


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF
    result = pipeline.analyze(path.read_bytes())

    print(f"== {path.name}")
    print(f"basis: {result.basis.value}")
    if is_unavailable(result.periods):
        print(f"periods: UNAVAILABLE ({result.periods.root().detail})")
        return 0
    print(f"periods: {[p.end_year for p in result.periods.ordered]}")

    print("\n== values")
    for v in result.values:
        # Name the inputs; never invent an operator here. FCF subtracts capex,
        # total_debt adds its parts, and the demo must not imply otherwise.
        origin = (
            f"page {v.source_page} {v.source_label!r}"
            if v.cell
            else f"derived from {', '.join(v.derived_from)}"
        )
        print(f"{v.concept.value:22} {v.period.end_year}  {v.value:>24,.2f}  {origin}")

    print("\n== metrics")
    for m in result.metrics:
        # Full precision is kept internally; rounding here is presentation only.
        print(f"{m.name:22} {m.period.end_year}  {m.value:.4f}")

    print("\n== reconciliations")
    for c in result.reconciliations:
        print(f"{c.status.value:12} {c.name:38} {c.period.end_year}  {c.detail}")

    print("\n== red flags")
    for f in result.red_flags:
        print(f"{f.outcome.value:14} {f.rule_id:24} {f.message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
