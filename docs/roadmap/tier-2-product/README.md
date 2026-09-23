# Tier 2: Product

**Goal:** make the provenance visible and useful. A reviewer should be able to type a ticker, see the
analysis in seconds, click any number and see the exact highlighted cell in the source PDF, see whether it
agrees with the SEC's own data, compare years across reports, and ask grounded questions.

**Entry condition:** the tier 1 exit gate has passed. Every tier-2 phase keeps running the dev eval in the gate.
Tier 2 must not move `wrong` either.

## Phases, in execution order

| Order | Phase | What it delivers |
|---|---|---|
| 1 | `T2.1-performance.md` | Measured speed-up on large reports with identical output |
| 2 | `T2.2-ticker-input-and-xbrl-crosscheck.md` | Analyse by ticker (US); per-value "matches SEC XBRL" badges |
| 3 | `T2.3-source-viewer.md` | Cell bounding boxes in provenance; click a value → page image with the cell highlighted |
| 4 | `T2.4-multi-report-trends.md` | Several reports of one company → multi-year series; restatements surfaced |
| 5 | `T2.5-grounded-qa.md` | Questions answered only from result evidence, same validator as the narrative, with its own eval set |

## Frontend decision (stated so nobody re-litigates it mid-tier)

Tier 2 is built **in Streamlit**. The source viewer (T2.3) is feasible there by rendering the PDF page to
an image with `pdfplumber`'s `page.to_image()` and drawing the cell rectangle. A Next.js rewrite costs weeks and
changes nothing a reviewer checks. It is kept as optional phase T3.3, to do *after* the product is proven.

## Tier 2 exit gate

1. Full `VERIFICATION_GATE.md` on `main`, dev eval unchanged or better.
2. Holdout eval re-run once. `wrong` must not be higher than at the tier 1 exit. Regenerate `docs/EVAL_RESULTS.md`.
3. Hosted demo redeployed and checked by hand: sample report, a ticker lookup (if enabled on hosted),
   the source viewer, a two-report trend, and Q&A with AI on. Record timings.
4. Re-run the adversarial audit prompt in a fresh session. Zero CRITICAL findings.
5. README screenshots updated for every new feature.
