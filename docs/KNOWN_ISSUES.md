# Known Issues and Open Decisions

Everything found during the Phase 0-8 build, the first manual runs, and two
deliberate stress-test passes. Ordered by severity. Each item says what it
is, how to reproduce it, why it happens, and what a fix costs.

Status as of 2026-09-12, commit `dd3e8a8`. 319 tests pass, Ruff clean.
The first stress pass found six defects; all six are fixed, each with a
regression test in `tests/test_stress_findings.py`. The second pass, run
against the fixed code, found nothing.

---

## Open - needs a decision

### 1. No plausibility check on any extracted number (MEDIUM)

`hostile.pdf` reports revenue of 999,999,999,999,999,999.00 crore. The system
accepts it, carries it exactly, and reports `low_confidence_kpi: clear`
because the row was matched deterministically from a real page.
`revenue_decline: clear` is likewise true - revenue went up, absurdly.

Defensible: confidence measures *how the row was identified*, not whether the
figure is believable, and a magnitude ceiling risks rejecting a legitimately
large report. But no layer asks "is this sane relative to its siblings?"

Since the fixes below, a figure past 400 significant digits is refused as
`UNPARSEABLE` rather than carried, so the ceiling is no longer unbounded -
but 400 digits is a representability limit, not a plausibility one.

**Options.** (a) Leave as is and document. (b) Add an INFO red flag when a
value is more than N orders of magnitude from the other values on the same
statement. (b) is new scope for a Phase 9+ brainstorming cycle, not a patch.

### 2. `types.py` is past its own review threshold (LOW)

610 lines against the ~600 line the plan set for revisiting the decision to
keep every contract in one file. Still coherent - the types reference each
other constantly - but worth reconsidering before Phase 9 adds narrative
types. A natural split is provenance/document types, analysis output types,
and the `Maybe`/`Unavailable` core.

### 3. Two verification gaps (LOW)

- **The live model test has never run.** `test_ollama_contract` is marked
  `@pytest.mark.ollama`, deselected by default and in CI. It needs a running
  Ollama with `qwen2.5:3b`. The six rejection paths *are* tested against a
  scripted fake; what is untested is whether a real `qwen2.5:3b` returns
  schema-valid JSON in practice. Run with `uv run pytest -m ollama`.
- **CI has never executed.** `.github/workflows/ci.yml` is committed but the
  repository has no remote, so GitHub Actions has never run it. The same
  sequence passes locally.

---

## Resolved - fixed in `2ea19cd` and `dd3e8a8`

### A. A malformed model response crashed the whole pipeline (was HIGH)

Spec 6.3 requires garbage model output to leave the concept unmapped and the
pipeline to continue. It did not: deeply nested JSON raised `RecursionError`,
which the validator's `except (ValueError, TypeError)` did not catch, and the
validator call sat outside the failure-isolation `try` in `fill_unmapped`.
This was the one finding that violated the written spec rather than a gap
in it.

**Fix.** The validator now caps the response at 64KB, fences the entire
parse-and-shape section with a catch-all, and walks the parsed value
iteratively rather than recursively - at roughly 2,000 levels the C decoder
succeeds and it was the recursive numeric check that overflowed, a boundary
an untrusted model gets to choose. The validator call also moved inside the
`try`. Regression: `test_garbage_model_output_leaves_pipeline_intact`
(nested bomb and 5MB blob), `test_deep_nesting_is_rejected_not_raised` at
200, 2,000, 5,000 and 100,000 levels.

### B. Ratios hid distress when both sides were negative (was HIGH)

Two negatives cancelled: a loss of 12,455 over average equity of -5,650
displayed ROE of +2.2044, and operating cash flow -100 over net income -50
displayed 2.0 as "earnings quality". Spec 7.1 had guarded exactly this trap,
but only for debt-to-equity. The code matched the spec; the spec had the gap.

**Fix.** Negative average equity or assets make ROE / ROA
`Unavailable(AMBIGUOUS)`; non-positive net income makes `ocf_to_net_income`
`Unavailable(AMBIGUOUS)`. Negative OCF against a *profit* stays computable
and reads as bad, honestly. An AMBIGUOUS verdict now passes through the
ratio helper unchanged instead of being relabelled as a missing input. Spec
7.1 amended. The `earnings_quality` rule against a loss now reports
`not_evaluated` with the reason rather than a silent `clear`. Regression:
`test_roe_with_negative_average_equity_is_ambiguous_not_positive`,
`test_roa_with_negative_average_assets_is_ambiguous`,
`test_ocf_to_net_income_with_a_loss_is_ambiguous`,
`test_hostile_roe_is_no_longer_a_tidy_positive`.

### C. Numerals from other scripts were silently accepted (was MEDIUM)

`parse_number("१२,४५०.००")` returned `12450.00`. The grammars used `\d`,
which in Python matches every Unicode decimal digit, so a Devanagari or
Arabic-Indic token passed a grammar the spec calls explicit, and `raw_token`
showed different glyphs from the number that was used.

**Fix.** Every grammar and year pattern uses `[0-9]`. Non-ASCII numerals are
`UNPARSEABLE`, matching the spec's stated stance. Regression:
`test_non_ascii_numerals_are_unparseable`,
`test_non_ascii_digits_never_form_a_year`.

### D. Unit scaling silently rounded past 28 significant digits (was LOW-MED)

Multiplying a figure by its scale ran in Python's default 28-digit context.
A 29-digit token times 10^7 became `1.0E+36` - rounded *up* across an order
of magnitude, with no `Unavailable`. Derived sums and the ROA/ROE average had
the same exposure. No real figure is anywhere near 28 digits, so nothing was
affected in practice, but the system's core claim is exact arithmetic end to
end and here exactness ended silently.

**Fix.** Scaling, derived sums and differences, and the averaging step run in
an exact context (400 digits) that traps on inexactness; a figure that
cannot be represented becomes `Unavailable(UNPARSEABLE)` rather than a
rounded number. Only division rounds, at the declared 34 digits. Spec 7.1
amended. Regression: `test_scale_multiplication_is_exact_at_any_width` at
20, 28, 29, 40 and 120 digits; `test_derived_sums_are_exact_past_28_digits`.

### E. Duplicate JSON keys let a model's decline be overridden (was LOW)

`{"source_row_id": null, "source_row_id": "page_1_..."}` resolved last-wins
to the pick. A response that declines and picks at once is malformed.

**Fix.** Duplicate keys are rejected via an `object_pairs_hook`. Regression:
`test_duplicate_json_keys_are_rejected`.

### F. Only years 1900-2099 were recognised (was LOW)

Widened to 1900-2199; still refuses 1899 and earlier. Regression:
`test_years_in_the_2100s_parse`.

### G. `demo.py` printed a fabricated operator (was HIGH, fixed in `f5cd561`)

The demo joined a derived value's inputs with `" + "`, printing
`free_cash_flow = operating_cash_flow + capex` when free cash flow in fact
*subtracts* capex. The stored value was always correct; only the label was
wrong. Now prints `derived from operating_cash_flow, capex` and never implies
an operation.

---

## What was attacked and held

Two passes. The first found A-F above. The second, run after the fixes,
found nothing. Everything below behaved correctly in both and is recorded so
the same ground is not covered twice.

| Attack | Result |
|---|---|
| 16 ingestion attacks: empty file, magic bytes only, truncated at 1KB and 90%, smashed trailer, smashed xref, null bytes, HTML, random bytes after a valid header | every one refused with a named error; no crash, no partial parse |
| Size and page caps at 1, 0, exact, and negative limits | boundaries correct - exact limits allowed, anything over refused |
| `inf`, `-inf`, `nan`, `Infinity`, `1e999`, `0x1F`, `1/2`, `1_000`, `1.2.3`, `,`, `.`, `1,,000` | all `UNPARSEABLE`; no infinity or NaN can enter the system |
| Zero-width space, byte-order mark, non-breaking space in a cell | refused or treated as missing, never guessed |
| 500-digit and 100,000-digit numeric tokens | parse exactly; a 300,000-digit token is refused at scaling as `UNPARSEABLE` (400-digit exact limit) rather than rounded |
| A stitched table spanning 1,000 consecutive pages | merged into one, no recursion, no slowdown |
| Tables with zero rows, headerless tables, a one-column header, an empty header | all handled; period detection returns `AMBIGUOUS` rather than failing |
| `1E+300 / 1E-300` and `1E-300 / 1E+300` in a ratio | `1E+600` and `1E-600`, both exact, no overflow |
| Equity of exactly zero, and an average equity of exactly zero from +100 and -100 | `DIVISION_BY_ZERO`, correctly refused |
| A well-formed PDF containing narrative only, no financial statements | survived: basis `unknown`, zero values, all ten rules `not_evaluated` with reasons |
| Prompt injection inside a model's `reasoning` field | ignored - only `source_row_id` is read, and Python fetches the number |
| Hallucinated row ID, wrong-statement row ID, already-claimed row, numeric field, bare null/string/list/number/true, NUL byte in an ID, 1MB ID string, `NaN` and `Infinity` literals, nesting at 200 / 2,000 / 5,000 / 100,000 levels, duplicate keys | all rejected by the gate; nothing raises |
| Row-ID uniqueness across all seven text-bearing fixtures (638 rows) | zero collisions |
| Runtime | hostile.pdf (18 pages, 500-row note) 2.9s; golden_indian.pdf (60 pages) 1.3s |

---

## Accepted deviations - no action planned

Each differs from the written plan on purpose and is recorded in the relevant
fixture's expected-value file.

| Deviation | Reason |
|---|---|
| `hostile.pdf` uses an 18-digit value, not the planned 10^99 | A 100-digit token cannot render inside a 149-point table cell. It overflowed into the label column and the PDF reader merged the glyphs, destroying the row the test depends on. 18 digits is still far past the exactness of ordinary 64-bit numbers, which is the point of the case. |
| A mapped `capex` keeps the document's negative sign | The plan's expected file listed a positive magnitude, but the core invariant is that a mapped value must equal its source cell exactly. Spec 7.2 puts sign normalisation at free-cash-flow derivation, which is where it now happens. Spec won over plan. |
| `hostile.pdf`'s balance sheet balances | The plan asserted it would not. 5,100 - 820 = 4,280, so it does. The reconciliation *warning* path is covered by unit tests on constructed inputs instead. |
| Three-year income statements against two-year balance sheets | Not a deviation but worth restating: `golden_us.pdf` reproduces the real 10-K shape, which is why `PeriodMap` is keyed per statement and why 2022 ROA, ROE and total debt are correctly `unavailable`. |

---

## Reproducing any of this

```bash
uv run python demo.py tests/fixtures/hostile.pdf
uv run python demo.py tests/fixtures/golden_indian.pdf
uv run python demo.py tests/fixtures/golden_us.pdf
uv run pytest tests/test_stress_findings.py -v
```
