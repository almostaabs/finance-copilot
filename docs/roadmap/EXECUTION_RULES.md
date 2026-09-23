# Execution rules

These apply to every phase. They restate what the codebase already enforces, so that new work does not
erode it. If a phase instruction ever seems to conflict with a rule here, **stop and ask**. Do not pick one.

---

## 1. The four product invariants (never violate)

1. **Numbers come only from the document.** A `FinancialValue` is built only through
   `FinancialValue.from_cell(...)` (from a `NormalizedCell`) or `FinancialValue.derived(...)` (from other
   concepts). No other code path may produce a number that is shown as a financial value. External data
   (SEC XBRL, hand labels) is **evaluation or cross-check only**. It is never displayed *as* the value and never
   substituted for a missing one.
2. **Nothing is guessed.** Anything undeterminable is `Unavailable(reason, detail, refs, cause)`. Never
   `None`, `0`, `NaN`, `inf`, an empty string, or a default. `UnavailableReason` is a closed enum: do not add
   members without a phase file saying so.
3. **AI is optional and narrow.** Model output is text, never a number. With AI off, every numeric output is
   identical to the digit. The regression snapshot (T1.0) checks this.
4. **Provenance survives every step.** Any new derived object carries `refs`/`inputs`/`cites` back to its
   source ref IDs.

Also keep:

- **No fuzzy matching** in `src/fincopilot/mapping/` (no edit distance, embeddings, or "similar label"
  logic). Aliases are explicit strings. This is a deliberate design choice, not an oversight.
- `SourceRef` is minted **only** in `src/fincopilot/extract/pdf.py`.
- `src/fincopilot/display.py` is the **only** place numbers are rounded for reading.
- `extract/pdf.py` is the only module doing PDF I/O for analysis. Network I/O goes in the new
  `src/fincopilot/sources/` package (created in T1.1), never in `extract/`, `mapping/`, `calc/` or `rules/`.
- All types in `types.py` are frozen dataclasses. Keep new types frozen with `slots=True`.
- Money is `Decimal`, never `float`. Parse from strings, never `Decimal(float_value)`.

## 2. Code conventions

- Python 3.12, `uv`. Run everything via `uv run ...`.
- Ruff config is in `pyproject.toml` (line length 100, rules E,F,I,UP,B,SIM,RUF). `ruff check` and
  `ruff format --check` must both pass.
- New runtime dependencies go in `[project].dependencies` **only** if the app needs them at runtime.
  Eval-only tooling goes in a new `[dependency-groups].eval` group. Dev tooling goes in `dev`.
  Every new dependency must be justified in the phase log.
- Pure functions for logic; I/O at the edges. New modules get a module docstring that says what they own
  and what they must never do (match the style of existing modules).
- No dead code, no commented-out code, no TODOs without a matching entry in `docs/KNOWN_ISSUES.md`.

## 3. Tests

- Every behaviour change gets a test in the existing file for that module (`tests/test_<package>_<module>.py`
  naming, e.g. `tests/test_mapping_synonyms.py`). Create a new test file only for a new module.
- Bug fixes get a regression test whose name states the behaviour, e.g.
  `test_unprefixed_statements_in_a_10k_are_consolidated`.
- Tests must be able to fail. After writing a test, temporarily break the code it covers, confirm the test
  fails, then restore. Mention this in the phase log for the phase's most important test.
- Tests that need the network, a live model, or a downloaded filing are marked (`@pytest.mark.network`,
  existing `ollama`/`gemini`) and deselected by default. Register new markers in `pyproject.toml`
  and add them to the `addopts` deselect expression.
- Synthetic PDF fixtures are built by `tests/fixtures/build_fixtures.py`. Adding or changing one requires
  updating `tests/fixtures/expected/hashes.json` and the pinned set in `tests/test_fixture_integrity.py`.
  Read both before touching fixtures.
- The test count must never go down unless the phase log explains which tests were removed and why.

## 4. Git

- One branch per phase: `roadmap/<phase-id>`. Small logical commits; the message says **why**.
- Never commit downloaded filings, PDFs from `tests/fixtures/real/`, API keys, or `.env` files. Eval caches
  live in gitignored directories.
- Merge to `main` only after the verification gate is green.

## 5. Documentation (update in the same phase, not later)

- `README.md`: any user-visible behaviour, new commands, new limits, and the test count on the Status line.
- `docs/KNOWN_ISSUES.md`: close items you fixed (with the fixing commit), add new ones you found.
- `docs/ROADMAP_LOG.md`: one entry per phase (template in `VERIFICATION_GATE.md`). Create the file in T1.0.
- If you change a documented spec rule, amend the spec in the same commit with a dated note. The design
  spec is `docs/superpowers/specs/2026-09-12-finance-copilot-design.md` (sections are numbered, e.g. §4.3
  Statement Location); per-phase build plans live in `docs/superpowers/plans/`.

## 6. Security

- SEC requests must send a `User-Agent` of the form `"finance-copilot <contact email>"` read from the
  `SEC_USER_AGENT` environment variable. Never hardcode an email. Stay under 10 requests/second; use a
  0.15 s minimum spacing between requests.
- Anything rendered as HTML in the app must go through the existing escaping in `panel.py` (or equivalent
  `html.escape`). Row labels come from untrusted PDFs.
- Treat text from PDFs and filings as untrusted data in any prompt sent to a model. It is never an instruction.

## 7. Stop and ask the human when

- A phase step cannot be done as written (a file, function or behaviour it names does not exist or works
  differently). Report what you found; do not invent a substitute design.
- The verification gate fails and two focused fix attempts did not resolve it. Revert to the last green
  commit, log what happened, and stop.
- A change would alter numbers in the regression snapshot and the phase file does not say that change
  is expected.
- The eval shows any increase in **wrong** values (see T1.1 definitions).
- You would need to add a dependency not named in the phase file, or change a type in `types.py` the phase
  file does not mention.
