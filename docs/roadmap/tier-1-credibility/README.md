# Tier 1: Credibility

**Goal:** turn "every number is right, or it says why it's missing" from a design claim into a measured
result, and fix the known correctness gaps that the measurement will expose.

Everything in tiers 2 and 3 depends on this tier. A viewer that highlights the source of a wrong number
is worse than no viewer.

## Phases, in execution order

| Order | Phase | What it delivers |
|---|---|---|
| 1 | `T1.0-baseline-and-snapshot.md` | `scripts/snapshot.py` + committed snapshot = the mechanical "did anything break?" check |
| 2 | `T1.1-xbrl-eval-harness.md` | `evals/` package: fetch SEC filings, render to PDF, score against XBRL. Dev/holdout split. Baseline numbers. |
| 3 | `T1.4-correctness-fixes.md` | 10-K unprefixed statements → consolidated; new `implausible_magnitude` INFO rule |
| 4 | `T1.2-indian-labeled-set.md` | ~15 hand-verified Indian reports as a second truth source in the same harness |
| 5 | `T1.3-eval-driven-coverage.md` | Alias/blocklist growth driven by dev-set failures; `docs/EVAL_RESULTS.md` scoreboard; README accuracy section |

(T1.4 runs before T1.2 on purpose: its basis fix changes US results, and it is cheaper to label Indian
reports once the pipeline's behaviour has settled.)

## Key definitions used across the tier (fixed; do not redefine)

For one (filing, concept, period) where ground truth exists:

| Outcome | Meaning |
|---|---|
| `correct` | The app produced a mapped value and it matches the truth within tolerance |
| `wrong` | The app produced a mapped value and it does **not** match the truth. **This is the number that matters.** |
| `withheld` | The app returned `Unavailable` (any reason) |
| `sign_mismatch` | abs(value) matches but the sign differs; counted inside `wrong`, reported separately |
| `wrong_period` | The app's value matches the truth of a *different* period of the same concept; counted inside `wrong`, reported separately |

- **precision** = correct / (correct + wrong)
- **coverage** = (correct + wrong) / (correct + wrong + withheld)
- **wrong rate** = wrong / (correct + wrong + withheld)

Truth cells where the truth source has no value are `no_truth` and are excluded from every ratio.

## Tier 1 exit gate (run after T1.3, before any tier-2 work)

1. Full `VERIFICATION_GATE.md` on `main`.
2. Holdout eval, run once: `uv run python -m evals.run --split holdout`. Record the results in
   `docs/EVAL_RESULTS.md` exactly as produced. **Do not fix anything based on holdout failures in this tier**:
   log them in `docs/KNOWN_ISSUES.md` for later. Looking at holdout failures and then fixing them turns the
   holdout into a second dev set and makes the published number dishonest.
3. Re-run the adversarial audit prompt (the one that writes `docs/AUDIT_<date>.md`) in a fresh session or
   subagent. Zero CRITICAL findings is the bar to exit the tier.
4. README shows the accuracy table and links to `docs/EVAL_RESULTS.md`.
