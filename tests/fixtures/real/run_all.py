"""Run every real annual report in this folder and print a summary.

Not a test: these documents are not committed and can change under us. It is a
harness for judging extraction against reality, which is what Phase 12 is for.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pipeline

from fincopilot.types import Unavailable

HERE = Path(__file__).parent


def main() -> int:
    pdfs = sorted(HERE.glob("*.pdf"))
    if not pdfs:
        print("No PDFs here. See README.md for where they came from.")
        return 1
    for pdf in pdfs:
        started = time.perf_counter()
        try:
            result = pipeline.analyze(pdf.read_bytes())
        except Exception as exc:
            print(f"{pdf.name:26} FAILED {type(exc).__name__}: {exc}")
            continue
        elapsed = time.perf_counter() - started
        periods = (
            result.periods.root().detail[:40]
            if isinstance(result.periods, Unavailable)
            else ", ".join(str(p.end_year) for p in result.periods.ordered)
        )
        concepts = len({v.concept.value for v in result.values})
        fired = [f.rule_id for f in result.red_flags if f.outcome.value == "fired"]
        print(f"== {pdf.name}  ({elapsed:.0f}s, {result.basis.value})")
        print(f"   periods {periods} | concepts {concepts}/19 | metrics {len(result.metrics)}")
        print(f"   red flags fired: {', '.join(fired) or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
