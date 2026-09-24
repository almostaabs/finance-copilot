# Roadmap log

One entry per roadmap phase (see `docs/roadmap/`), appended in the order phases finish. Each entry
records the verification-gate results, test counts, snapshot changes, new dependencies and anything
skipped or blocked, using the template at the bottom of `docs/roadmap/VERIFICATION_GATE.md`. This file is
the audit trail: it is how a later reader can tell what each phase changed and why the gate passed.

## T1.0: Baseline and regression snapshot. PASS, 2026-09-23

- Branch / merge commit: `roadmap/t1-0-baseline` / `543f3fd`
- Tests: 451 → 454 passed, 2 deselected (removed: none)
- Lint/format: pass
- Snapshot: created. `tests/snapshots/fixtures.snap` (599 lines, 9 synthetic fixtures, committed) and
  `.snapshots/real.snap` (585 lines, gitignored); `--check` ok on both
- Eval (dev): n/a before T1.1
- App smoke: pass (`tests/test_app.py` 12 passed; `/_stcore/health` ok; "Load sample report" renders Results, no exception box)
- Invariant spot-check: 1 ✔ no `FinancialValue(` in new files; 2 ✔ script reads `Unavailable` only via `.root()`;
  3 ✔ no `round(`/`quantize` in new code; 4 ✔ no HTML output added; 5 ✔ no network/model calls added
- Acceptance criteria:
  1. `snapshot.py --check` exits 0 → exit 0 on 3 runs
  2. `HIGH_LEVERAGE` 2.0→0.1 → exit 1, diff shows `high_leverage` clear→fired on golden_indian, golden_us,
     standalone_only (and two real reports); restored
  3. determinism → 3 consecutive `--check` runs pass, identical line counts
  4. `tests/test_snapshot.py` has the 3 tests, all pass, count +3
  5. `DOCUMENT_ID_PATTERN` scan of `fixtures.snap` → no matches; test also asserts real `document_id`s absent
  6. `.snapshots/` ignored (`.gitignore:22`); `tests/snapshots/fixtures.snap` tracked
  - Phase-specific: `git diff master --stat -- src/ pipeline.py app.py` empty
- New dependencies: none
- Most important test and proof it can fail: `test_fixture_snapshot_matches`; with `HIGH_LEVERAGE` = 0.1 it
  failed (AssertionError), passed again after restore
- Known issues added/closed: none
- Surprises / notes for the next phase: the phase's original "no 32-hex-char token" check failed on correct
  output (ratios at `prec=34` give long digit runs); amended 2026-09-23 by human decision to a direct
  `document_id` check plus `DOCUMENT_ID_PATTERN`. Basis lives at `result.statements.basis`, not
  `result.basis`. A full `--check` takes ~5 min with the 6 local real reports (fixtures alone: seconds).
  Real reports present: 2025_AnnualReport, apple_10k_2023, berkshire_2023, merchants_bank_2024,
  microsoft_fy24, wipro_fy24. Default branch is `master`; roadmap "main" means `master`.

## fix/gemini-unicode: Gemini "UnicodeEncodeError". Out-of-band fix, PASS, 2026-09-24

- Branch / merge commit: `fix/gemini-unicode` / `d8f513e` (fix `d3db674`, docs `813dddb`)
- Cause: `GeminiClient` put the model name into the URL and the key into a header unchecked; a
  non-ASCII character there (non-breaking hyphen, NBSP, zero-width space) makes `http.client` raise
  `UnicodeEncodeError`, reported as "gemini request failed: UnicodeEncodeError". Not PDF- or OS-specific:
  the Apple prompt is pure ASCII and goes in the UTF-8 body.
- Exact trigger not confirmed: a live Apple run got HTTP 503 then a timeout, and the human did not know
  whether the model box was pasted ("Don't know; fix both"). Both mechanisms reproduced offline and covered.
  Follow-up check 2026-09-24: the key in `.streamlit/secrets.toml` is printable ASCII (39 chars) and
  `GEMINI_API_KEY` is unset, so the key is ruled out; a pasted model name remains the likely trigger.
- Fix: `complete_json` refuses a model or key with any character outside printable ASCII before any
  request, raising `LLMError` that names the field and code point (never the key), so callers decline as usual.
- Tests: 454 → 457 passed; `test_unsendable_model_or_key_is_named_before_any_request` fails 3/3 on the
  pre-fix client, passes after
- Lint/format: pass. Snapshot: no diff (fixtures 599, real 585). Eval: n/a. App smoke: pass
- Invariant spot-check: 1-5 ✔ (no new values, rounding, HTML or network calls; change is inside `ai/`)
- Known issues added: 0d, "-0.0% vs prior year" coloured red for a sub-rounding change

## T1.1: XBRL ground-truth eval harness. Gate pending

- Pilot hand check (step 7; AAPL 10-K, accession 0000320193-23-000106, rendered PDF), approved by the human
  2026-09-24 before the full dev run:

  | concept, year | app value | row label, page | XBRL value (tag) | filing shows | harness |
  |---|---|---|---|---|---|
  | revenue 2023 | 383,285,000,000 | Total net sales, p31 | 383,285,000,000 (RevenueFromContractWithCustomerExcludingAssessedTax) | 383,285 ($M) | correct ✔ |
  | total_assets 2022 | 352,755,000,000 | Total assets, p33 | 352,755,000,000 (Assets, end 2022-09-24) | 352,755 ($M) | correct ✔ |
  | capex 2021 | -11,085,000,000 | Payments for acquisition of property, plant and equipment, p35 | 11,085,000,000 (PaymentsToAcquirePropertyPlantAndEquipment) | (11,085) ($M) | correct ✔ (capex sign ignored) |
  | d_and_a 2023 | withheld (`not_mapped`) | none | 11,519,000,000 (DepreciationDepletionAndAmortization) | 11,519 on p35 | withheld ✔ (a real app gap) |

  Pilot wrong records: JPM total_assets and total_liabilities, p169, a VIE footnote table read as the
  balance sheet (KNOWN_ISSUES T1.1-a). AAPL is a holdout company, so it is marked exposed
  (`evals/exposed.json`) and kept out of headline holdout totals.
