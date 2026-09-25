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

## T1.1b: Eval-found bugs (T1.1-a, -d, -e, -g). PASS, 2026-09-24

- Branch / merge commit: `roadmap/t1-1b` / `b20ace8` (snapshot `35ff8bd`, dev baseline `b152c88`).
  Commits: `dc317d2` (T1.1-a, with the literal "Statements of Consolidated <X>" anchors), `e2d9499` (T1.1-e,
  reordered before T1.1-d by human decision), `b3e22f8` (T1.1-d), `f85dab5` (T1.1-g), `1cf0e45` (hygiene:
  `edgar.py` wraps `http.client.HTTPException`; `run.py` escapes `|`), `fbcf4a0` (docs).
- Gate run by a fresh evaluator (phase ID, roadmap paths and branch only); verdict PASS on the condition that
  the orchestrator updates the snapshot, done in `35ff8bd`.
- Tests: 519 -> 551 passed, 2 deselected (removed: none; `test_all_nine_fixtures_are_present` renamed to
  `test_every_pinned_fixture_is_present`). Before the snapshot update, `test_fixture_snapshot_matches` failed
  only on the new fixtures' added lines (amendment rule).
- Lint/format: pass
- Snapshot: fixtures.snap 599 -> 772 lines, ADDED lines only (173): `component_total.pdf` 54,
  `footnote_table.pdf` 57, `percent_sales.pdf` 62; 0 removed or changed. `.snapshots/real.snap`: 585 lines,
  0 changes. The fiscal reconcile (T1.1-g) was run by the evaluator on all 36 dev filings: 35 untouched
  (including LOW, NVDA, WMT, CRM, the December filers); only HD relabelled, each label quoting its p4 binding.
- App smoke: pass (`tests/test_app.py` 12 passed; `/_stcore/health` ok; browser click not checked)
- Invariant spot-check: 1 ✔ no new `FinancialValue(`; 2 ✔ undecidable cases are `Unavailable(AMBIGUOUS)`
  or `CONFLICT`, `types.py` unchanged; 3 ✔ no new rounding; 4 ✔ no new HTML, eval Markdown escapes `|`;
  5 ✔ network change only in `sources/edgar.py` (exception wrap)
- Acceptance criteria: 1-6 ✔. Break-and-restore by the evaluator: `_total_of` -> `None` fails
  `test_the_total_row_wins_over_its_component`; grid split disabled fails 2 textgrid tests incl.
  `test_footnote_table_under_the_balance_sheet_never_supplies_its_totals`; `%` sub-header branch disabled
  fails 3 incl. `test_percent_sales_fixture_maps_amounts_and_never_the_percentages`; reconcile early-return
  fails 4 periods tests (the date-only "untouched" test still passes, as it should)
- Most important test: `test_the_total_row_wins_over_its_component` (the general total-wins rule)
- New dependencies: none
- Eval (dev only, `--compare` against the T1.1 baseline; holdout not run):

  | scope | correct | wrong | withheld | unverified | precision | coverage |
  |---|---|---|---|---|---|---|
  | all | 632 -> 708 | 23 -> 0 | 536 -> 483 | 40 -> 37 | 0.9649 -> 1.0000 | 0.5500 -> 0.5945 |
  | general | 585 -> 654 | 19 -> 0 | 483 -> 433 | 36 -> 33 | 0.9685 -> 1.0000 | 0.5557 -> 0.6017 |
  | financial | 47 -> 54 | 4 -> 0 | 53 -> 50 | | 0.9216 -> 1.0000 | |

  New wrong records: 0. Every changed record:
  - wrong -> correct (23): JPM total_assets, total_liabilities 2024-2025; F cash 2024-2025; HON cogs
    2023-2025; LOW cogs, d_and_a, gross_profit, operating_income 2025-2026; HD cash, current_assets,
    current_liabilities, equity, total_assets, total_liabilities 2025.
  - withheld -> correct (53): BAC net_income 2023-2025; F cogs, net_income, revenue 2023-2025; UPS capex,
    d_and_a, net_income, operating_cash_flow, operating_income, revenue 2023-2025 and cash, current_assets,
    current_liabilities, total_assets 2024-2025 (26); DE revenue 2023-2025; TSLA revenue 2023-2025; WMT
    revenue 2024-2026; HD cash, current_assets, current_liabilities, equity, total_assets,
    total_liabilities 2024.
  - new unverified (4): DE cogs 2023-2025 (now mapped, no XBRL truth); HD short_term_borrowings 2024.
  - dropped (7): HD 2026 unverified records (cash, current_assets, current_liabilities, equity,
    short_term_borrowings, total_assets, total_liabilities); the balance-sheet date February 1, 2026 is now
    fiscal 2025.
- Proof each fix's tests can fail (fix reverted or disabled, tests run): anchors 5 fail; total-wins 1;
  aliases 3; % sub-column 3; fiscal reconcile 4 (disabled), 1 (clash check off); edgar wrap 1; `|` escape 1;
  word-grid split and paren/footnote tests fail on revert of `dc317d2`.
- Known issues: T1.1-a, -d, -e, -g moved to resolved with their commits. Added T1.1b-1 (MEDIUM): the scored
  fallback can pick a non-statement table when no anchor matches (UPS before the anchors).
- Human decisions and amendments (2026-09-24, in the phase file): bug 2 header includes the "Amount % Sales"
  sub-header; bug 4 = A (one-sentence binding, exact date match) with B fallback; bug 1 = split plus literal
  anchors; Deere revenue regression fixed as bug 3 via a general total-wins rule (Deere revenue now correct).
- Surprises / notes for the next phase: `_total_of` decides only two-way claims; three or more claims are
  withheld as CONFLICT. When the total wins, the component's claim is dropped without a conflict record.
  The KNOWN_ISSUES status line still reads "Phase 15, 451 tests" (stale, not touched here).

## T1.4: Correctness fixes (10-K basis, plausibility flag). PASS, 2026-09-25

- Branch / merge commit: `roadmap/t1-4` / `27728fb` (snapshot `812e7b4`). Commits: `93632b9` (phase-file
  amendments A1-A3, human decisions), `056f275` (A: 10-K cover basis), `7bc97e2` (B: `implausible_magnitude`),
  `eb7bd9a` (A2: `MappingNote` for the total-wins rule), `357d13c` (A3 docs).
- Gate run by a fresh evaluator (phase ID, roadmap paths and branch only); verdict PASS on the condition that
  the orchestrator updates the snapshot, done in `812e7b4`.
- Tests: 551 -> 574 passed, 2 deselected (removed: none; three "ten rules" assertions now expect eleven).
  Before the snapshot update, only `test_fixture_snapshot_matches` failed, on declared added lines.
- Lint/format: pass
- Snapshot: fixtures.snap 772 -> 911 lines, ADDED lines only (139): `unprefixed_10k.pdf` 126 (basis
  `consolidated`; every value identical to `golden_us.pdf`, only page numbers differ), 11
  `flag | implausible_magnitude` lines (hostile `fired`; ambiguous_periods, no_scale `not_evaluated`; the other
  8 `clear`; scanned.pdf is rejected before analysis), 2 `note` lines (component_total.pdf: cogs kept row_8
  over row_6, revenue kept row_4 over row_1). `.snapshots/real.snap` 585 -> 591: 6 added
  `flag | implausible_magnitude | clear info` lines, one per real report; **no real-report line changed**, every
  basis line unchanged (MSFT stays `standalone_fallback`).
- Eval (dev, `--compare` against the T1.1b baseline): no change. All 1228 records compared (value, outcome,
  ref_id): 0 changed. all: correct 708, wrong 0, withheld 483, unverified 37, precision 1.0000, coverage
  0.5945 (general 654/0/433, financial 54/0/50). Baseline not updated. Holdout not run.
- Basis changes under Part A (dev, branch vs master-equivalent run on the same extracted documents): none.
  34 consolidated, IBM unknown, MSFT standalone_fallback. All 33 EDGAR renders have a cover on page 1 but
  already had "Consolidated" anchors; BRK-B has a cover on p23 and was already consolidated.
- `implausible_magnitude` firings: no real company (dev: 31 clear, 5 not_evaluated "No periods." — META, IBM,
  CRM, COST, SBUX; real reports: 6 clear). Only the synthetic `hostile.pdf` fires: revenue 2023->2024 changed
  ~9.1e13x and revenue/total_assets 2024 ~2.3e14 (the 999,999,999,999,999,999 crore revenue of issue #1).
- App smoke: pass (`tests/test_app.py` 13 passed; `/_stcore/health` ok; browser click not checked)
- Invariant spot-check: 1 ✔ no new `FinancialValue(`; 2 ✔ rule returns `Unavailable(MISSING_INPUT, cause=...)`,
  zero divisor `DIVISION_BY_ZERO`, no enum members added; 3 ✔ no new rounding; 4 ✔ Provenance note label goes
  through `html.escape` (`test_provenance_shows_a_dropped_component_note_escaped`); 5 ✔ no network/model calls
- Acceptance criteria: 1-5 ✔ and amendments A1-A3 ✔. `types.py` changed only as A2 allows: new frozen
  `MappingNote` (uses existing `CanonicalConcept`, `StatementKind`) and `MappingReport.notes = ()`.
- Most important test and proof it can fail: `test_unprefixed_statements_in_a_10k_are_consolidated`; with
  `locate.py` reverted to master it failed (with the page-30 cover test). A2: suppressing note appends failed
  4 tests; letting the dropped claim win failed `test_the_total_row_wins_over_its_component` and both note
  tests. Removing the Washington regex failed the prose-only negative.
- New dependencies: none
- Known issues: #1 closed (option (b), via `implausible_magnitude`); PHASE12 "unprefixed statements" resolved
  for true 10-K filings; added T1.4-a (glossy annual report without a 10-K cover, e.g. MSFT, is labelled
  "standalone fallback" although consolidated; suggested fix, not implemented: show "basis not stated in
  document"). Status line updated to T1.4 / 574 tests. T1.1b note closed: the dropped component claim is now
  recorded as a `MappingNote` and shown in the Provenance tab.
- Human decisions and amendments (2026-09-25, in the phase file): A1 per-page cover rule (SEC name +
  "Washington, D.C. 20549" + "Form 10-K" on one page, any page) replaces "first 3 pages"; A2 structured
  `MappingNote`; A3 docs items. Parts A and B built sequentially by one builder on one branch, one gate run.
- Surprises / notes for the next phase: the MSFT file in `tests/fixtures/real/` and in the eval corpus is the
  glossy annual report, so Part A's original target (MSFT) does not move. A1's text says only Apple and
  Merchants have a full cover page; `berkshire_2023.pdf` also has one (p23), with no effect. Five dev companies
  resolve no periods for the flag (`not_evaluated`), worth a look in T1.3.
