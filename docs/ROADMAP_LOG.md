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
