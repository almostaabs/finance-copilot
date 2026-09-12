# Known Issues and Open Decisions

Everything found during the Phase 0-8 build, the first manual runs, and a
deliberate stress-test pass. Issues are ordered by severity. Each says what
it is, how to reproduce it, why it happens, and what a fix would cost.

Status as of 2026-09-12, commit `6603804`. 297 tests pass, Ruff clean.
Nothing here was found by the test suite — these are the gaps the suite does
not yet cover, which is the point of writing them down.

---

## Open - needs a decision

### 1. A malformed model response crashes the whole pipeline (HIGH)

Spec §6.3 is explicit:

> Ollama unreachable, timing out (10s), or returning garbage leaves the
> concept `UNMAPPED` and the pipeline continues.

It does not. A model returning deeply nested JSON takes the process down:

```python
class NestedBomb:
    def complete_json(self, prompt, schema):
        return "[" * 2000 + "]" * 2000

pipeline.analyze(pdf_bytes, llm=NestedBomb())
# RecursionError: maximum recursion depth exceeded
```

**Why it happens.** Two gaps line up. `validate_response` wraps `json.loads`
in `except (ValueError, TypeError)`, but deep nesting raises `RecursionError`,
which is neither. And in `fill_unmapped` the call to `validate_response` sits
*outside* the `try` that guards the model call, so nothing catches it either.
The six-path rejection gate is sound; the failure happens before the gate
gets to run.

**Severity.** The model is untrusted by design — the entire validation gate
exists because a small local model may return anything. This is the one
finding that is a violation of the written spec rather than a gap in it.

**Fix.** Catch `RecursionError` (or simply `Exception`) around the JSON parse
in `validate_response`, and move the `validate_response` call inside the
existing `try` in `fill_unmapped`. Roughly four lines plus two tests. There
is a case for also capping response size before parsing.

### 2. Ratios hide distress when both sides are negative (HIGH)

Two negatives cancel and a failing company shows a healthy ratio.

```
net_income 2024                            -12,455,000,000   (a loss)
average equity  (-8,200,000,000 + -3,100,000,000) / 2  =  -5,650,000,000
roe 2024        -12,455 / -5,650  =  +2.2044             (reads as +220% return)
```

Reproduce with `uv run python demo.py tests/fixtures/hostile.pdf`. The same
cancellation affects `ocf_to_net_income`: operating cash flow −100 against
net income −50 gives +2.0, which reads as excellent earnings quality for a
company burning cash.

**Why it happens.** Spec §7.1 identified exactly this trap and guarded it,
but only for debt-to-equity:

> **Negative equity** -> D/E is `Unavailable(AMBIGUOUS, ...)`. A distressed
> company would otherwise display a tidy negative D/E that reads as *low*
> leverage. This is an analytical trap, not a math one.

No equivalent guard exists for `roe`, `roa`, or `ocf_to_net_income`. The code
matches the spec exactly; the spec has the gap. A denominator of exactly zero
*is* handled (`DIVISION_BY_ZERO`) — only the negative case slips through.

**Scope.** `roe` (negative average equity), `ocf_to_net_income` (both figures
negative), and in principle `roa`. The `earnings_quality` red-flag rule
already refuses to fire unless both figures are positive, so the *rule* is
safe. The displayed *metric* is not, and Phase 10's dashboard would show it.

**Fix.** Mirror the D/E guard in `src/fincopilot/calc/ratios.py`, amend spec
§7.1, add about three tests, update two hostile-fixture assertions.

### 3. Numerals from other scripts are silently accepted (MEDIUM)

```
parse_number("१२,४५०.००")  ->  Decimal("12450.00")     # Devanagari
parse_number("١٢٣")         ->  Decimal("123")          # Arabic-Indic
```

**Why it happens.** The grammars use `\d`, which in Python matches any
Unicode decimal digit, and `Decimal()` accepts them too. The spec promises
the opposite:

> Both grouping conventions are parsed by **explicit grammar**, never by
> heuristic guessing. … If a string satisfies neither grammar, the result is
> `Unavailable(UNPARSEABLE)`. No best guess.

**Why it matters.** Indian filings use Latin numerals, so a Devanagari digit
in a financial table is far more likely to be an extraction artifact or
planted content than a real figure. Accepting it creates a provenance
mismatch: `raw_token` shows `१२,४५०.००` while `value` is 12450.00, so a human
checking the source sees different glyphs from the number that was used. It
also quietly widens the grammar beyond what was agreed.

**Fix.** Replace `\d` with `[0-9]` in the three grammar patterns (or compile
them with `re.ASCII`). One line each, plus a test. Decide first whether
non-Latin numerals should be *refused* or *transliterated* — refusing matches
the spec's stated stance.

### 4. No plausibility check on any extracted number (MEDIUM)

`hostile.pdf` reports revenue of 999,999,999,999,999,999.00 crore. The system
accepts it, carries it exactly, and reports `low_confidence_kpi: clear`
because the row was matched deterministically from a real page.
`revenue_decline: clear` is likewise true — revenue went up, absurdly.

Defensible: confidence measures *how the row was identified*, not whether the
figure is believable, and a magnitude ceiling risks rejecting a legitimately
large report. But no layer anywhere asks "is this sane relative to its
siblings?" There is also no length cap on a numeric token — a 300,000-digit
string parses without complaint.

**Options.** (a) Leave as is and document. (b) Add an INFO red flag when a
value is more than N orders of magnitude from the other values on the same
statement. (b) is new scope for a Phase 9+ brainstorming cycle, not a patch.

### 5. Unit scaling silently rounds past 28 significant digits (LOW-MEDIUM)

Converting a figure to base units multiplies it by its scale, and that
multiplication runs in Python's *default* decimal context (28 digits), not in
the project's declared 34-digit `RATIO_CONTEXT`:

```
29-digit token x 10^7  ->  1.000000000000000000000000000E+36
exact answer           ->    999999999999999999999999999990000000
```

The result is not merely truncated, it rounds up across an order-of-magnitude
boundary, and no `Unavailable` is raised.

**When it bites.** Only above 28 significant digits. Every realistic figure is
far below that (12,450.00 crore is 14 digits, and even the hostile fixture's
18-digit value is safe), so no current test or fixture is affected. It is
logged because the system's core claim is exact decimal arithmetic end to
end, and here exactness ends silently rather than reporting that it did.

**Fix.** Perform the scale multiplication in an explicit context, and decide
what should happen when a value genuinely exceeds it - almost certainly
`Unavailable(UNPARSEABLE)` rather than a rounded number.

### 6. Duplicate JSON keys let a model's decline be overridden (LOW)

```
{"source_row_id": null, "source_row_id": "page_1_table_0_row_0"}   ->  ACCEPTED
```

Python's JSON parser keeps the last value for a repeated key, so a response
containing both an explicit decline and a pick resolves to the pick. Spec
6.3 calls `null` a *mandatory explicit decline option*; a response that
declines and picks at once is malformed and should be rejected outright
rather than silently resolved.

**Fix.** Reject on duplicate keys via an `object_pairs_hook`. A few lines and
one test. Low priority: it needs a model that emits invalid-ish JSON, and the
resulting pick still passes all six validation paths, so it can only ever
select a real row from the correct statement.

### 7. Only years 1900-2099 are recognised (LOW)

`parse_period` accepts 1900-2099 and refuses anything outside, because the
year pattern is `(?:19|20)\d{2}`. 2100 and later become
`Unavailable(AMBIGUOUS)`. Correct and safe for the foreseeable life of the
tool - recorded so nobody rediscovers it as a mystery in 2100, and because a
report containing a stray far-future date in a header will refuse the whole
document rather than that one column.

### 8. `types.py` is past its own review threshold (LOW)

610 lines against the ~600 line the plan set for revisiting the decision to
keep every contract in one file. Still coherent - the types reference each
other constantly - but worth reconsidering before Phase 9 adds narrative
types. A natural split is provenance/document types, analysis output types,
and the `Maybe`/`Unavailable` core.

### 9. Two verification gaps (LOW)

- **The live model test has never run.** `test_ollama_contract` is marked
  `@pytest.mark.ollama`, deselected by default and in CI. It needs a running
  Ollama with `qwen2.5:3b`. The six rejection paths *are* tested against a
  scripted fake; what is untested is whether a real `qwen2.5:3b` returns
  schema-valid JSON in practice. Run with `uv run pytest -m ollama`.
- **CI has never executed.** `.github/workflows/ci.yml` is committed but the
  repository has no remote, so GitHub Actions has never run it. The same
  sequence passes locally.

---

## What was attacked and held

The stress pass tried to break each stage on purpose. Everything below
behaved correctly and is *not* an issue - recorded so the same ground is not
covered twice.

| Attack | Result |
|---|---|
| 16 ingestion attacks: empty file, magic bytes only, truncated at 1KB and 90%, smashed trailer, smashed xref, null bytes, HTML, random bytes after a valid header | every one refused with a named error; no crash, no partial parse |
| Size and page caps at 1, 0, exact, and negative limits | boundaries correct - exact limits allowed, anything over refused |
| `inf`, `-inf`, `nan`, `Infinity`, `1e999`, `0x1F`, `1/2`, `1_000`, `1.2.3`, `,`, `.`, `1,,000` | all `UNPARSEABLE`; no infinity or NaN can enter the system |
| Zero-width space, byte-order mark, non-breaking space in a cell | refused or treated as missing, never guessed |
| 500-digit and 100,000-digit numeric tokens | parsed exactly, no hang |
| A stitched table spanning 1,000 consecutive pages | merged into one, no recursion, no slowdown |
| Tables with zero rows, headerless tables, a one-column header, an empty header | all handled; period detection returns `AMBIGUOUS` rather than failing |
| `1E+300 / 1E-300` and `1E-300 / 1E+300` in a ratio | `1E+600` and `1E-600`, both exact, no overflow |
| Equity of exactly zero, and an average equity of exactly zero from +100 and -100 | `DIVISION_BY_ZERO`, correctly refused |
| A well-formed PDF containing narrative only, no financial statements | survived: basis `unknown`, zero values, all ten rules `not_evaluated` with reasons |
| Prompt injection inside a model's `reasoning` field | ignored - only `source_row_id` is read, and Python fetches the number |
| Hallucinated row ID, wrong-statement row ID, already-claimed row, numeric field, bare null/string/list/number/true, NUL byte in an ID, 1MB ID string, `NaN` and `Infinity` literals | all rejected by the six-path gate |
| Row-ID uniqueness across all seven text-bearing fixtures (638 rows) | zero collisions |
| Runtime | hostile.pdf (18 pages, 500-row note) 2.9s; golden_indian.pdf (60 pages) 1.3s |

---

## Resolved during this session

### `demo.py` printed a fabricated operator (was HIGH, fixed in `f5cd561`)

The demo joined a derived value's inputs with `" + "`, printing
`free_cash_flow = operating_cash_flow + capex` when free cash flow in fact
*subtracts* capex. The stored value was always correct (1,210 - 540 = 670);
only the printed label was wrong. Now prints
`derived from operating_cash_flow, capex` and names inputs without implying
an operation.

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
```

Issues 1, 3, 5 and 6 have no fixture; the reproduction snippets are inline
above. None of them is covered by the test suite yet - adding those tests is
part of each fix.
