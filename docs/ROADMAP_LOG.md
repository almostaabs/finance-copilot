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

## T1.1: XBRL ground-truth eval harness. PASS, 2026-09-24

- Branch / merge commit: `roadmap/t1.1` / `aa4a6d9` (dev baseline `2c99a38`, generated at `af8cc61`)
- Tests: 457 → 519 passed, 2 deselected (removed: none)
- Lint/format: pass
- Snapshot: no diff (fixtures 599, real 585); no snapshot update
- Eval (dev, 36 companies, 0 errors; split dev 36 / holdout 14):

  | scope | correct | wrong | withheld | unverified | precision | coverage |
  |---|---|---|---|---|---|---|
  | all | 632 | 23 | 536 | 40 | 0.9649 | 0.5500 |
  | general | 585 | 19 | 483 | 36 | 0.9685 | 0.5557 |
  | financial | 47 | 4 | 53 | 4 | 0.9216 | 0.4904 |

  Wrong: 17 `value`, 6 `wrong_period`, 0 `sign_mismatch`. By root cause: HD balance sheet vs "Fiscal"
  statements 6 (T1.1-g); LOW "% Sales" column read as amounts 8 (T1.1-d); HON component row taken over the
  total 3 (T1.1-e); VIE footnote tables, JPM 4 and F 2 (T1.1-a). `--compare` on an unchanged tree: no
  change, exit 0. Holdout not run.
- App smoke: pass (`tests/test_app.py` 12 passed; `/_stcore/health` ok; browser click not checked)
- Invariant spot-check: 1 ✔ no new `FinancialValue(`; 2 ✔ no `None`/`0` for `Unavailable`; 3 ✔ only
  rounding is eval ratios in `evals/score.py`; 4 ✔ no app HTML, `render.py` escapes `<base href>`;
  5 ✔ network only in `sources/edgar.py` (and pre-existing `ai/client.py`)
- Acceptance criteria: 1-7 ✔ (criterion 1: suite passes with non-localhost sockets blocked; no test yet
  carries the `network` marker)
- Hand checks (evaluator, random): wrong JPM total_assets 2024 (p169 VIE table), HD total_assets and cash
  2025 (p44, `wrong_period`), F cash 2024 (p116 VIE table), HON cogs 2023 (p59): all real app errors, none
  a harness error. Correct UNH revenue and cogs 2024, MBIN net_income 2024, VZ cash 2024: confirmed.
- New dependencies: `playwright>=1.45` in the `eval` dependency group only (Chromium installed by hand into
  `%LOCALAPPDATA%\ms-playwright` after CDN timeouts)
- Most important test and proof it can fail: `test_correct_exactly_at_the_tolerance_boundary`; with `<=`
  changed to `<` in `evals.score._matches` it failed; `MIN_ANNUAL_DAYS = 0` failed
  `test_quarterly_facts_are_dropped`
- Known issues added: T1.1-a (VIE footnote tables, HIGH), T1.1-b (XOM CIK), T1.1-c (rendered-PDF caveat),
  T1.1-d (LOW "% Sales", HIGH), T1.1-e (HON cogs, HIGH), T1.1-f (net-income basis, MEDIUM), T1.1-g (HD years)
- Human decisions and amendments (2026-09-24): XOM hand-locked to CIK 0000034088, accession
  0000034088-26-000045 (the ticker maps to a new holding company). Criterion 7 amended: `ai/client.py`
  predates the phase. AAPL, viewed in the pilot hand check, is marked exposed and kept out of headline
  holdout totals. `ProfitLoss` accepted for net_income. Truth year (fact 4) is rule C1: `year(end)` by
  default, plus a per-ticker `fiscal_year_offset` in `evals/corpus.csv` only with page-and-header evidence
  (HD only: -1, p45 and p48 "Fiscal 2025"; an earlier draft cited p44, which is the dated balance sheet).
  A pure `fy`-derived offset was tried and rejected: LOW and CRM carry an `fy` one below their printed
  naming. Each run prints an `fy`-mismatch listing (dev: CRM, LOW); the tier-1 exit gate checks holdout
  headers from it before the holdout run.
- Surprises / notes for the next phase: coverage (0.55) is limited mostly by withheld concepts, not wrong
  ones. `edgar.py` catches `(OSError, ValueError)`, so an `http.client.IncompleteRead` escapes unwrapped
  (run.py still records it as an error). `run.py` Markdown tables do not escape `|` in row labels.

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
