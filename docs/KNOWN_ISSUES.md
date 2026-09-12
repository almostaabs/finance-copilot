# Known Issues and Open Decisions

Everything found during the Phase 0-8 build and the first manual runs.
Nothing here is a crash or a wrong stored number; the issues are about
figures that are *arithmetically correct but analytically misleading*, plus
housekeeping. Each item says what it is, how to see it, and what fixing it
would cost.

Status as of 2026-09-12, commit `f5cd561`. 297 tests pass, Ruff clean.

---

## Open - needs a decision

### 1. Ratios can hide distress when both sides are negative (HIGH)

When a numerator and denominator are *both* negative, the minus signs cancel
and a bad company displays a healthy-looking positive ratio.

Seen in `hostile.pdf`:

```
net_income 2024                            -12,455,000,000   (a loss)
average equity  (-8,200,000,000 + -3,100,000,000) / 2  =  -5,650,000,000
roe 2024        -12,455 / -5,650  =  +2.2044             (reads as +220% return)
```

The same cancellation affects `ocf_to_net_income`: operating cash flow −100
against net income −50 gives +2.0, which reads as excellent earnings quality
for a company burning cash.

**Why it happens.** Spec §7.1 identified exactly this trap and guarded it,
but only for debt-to-equity:

> **Negative equity** -> D/E is `Unavailable(AMBIGUOUS, ...)`. A distressed
> company would otherwise display a tidy negative D/E that reads as *low*
> leverage. This is an analytical trap, not a math one.

No equivalent guard was written for `roe`, `roa`, or `ocf_to_net_income`.
The code matches the spec exactly; the spec has the gap.

**Scope.** `roe` (negative average equity), `ocf_to_net_income` (both
figures negative), and in principle `roa` (negative average assets, rare in
practice). The `earnings_quality` red-flag rule already refuses to fire
unless both figures are positive, so the *rule* is safe. The displayed
*metric* is not, and Phase 10's dashboard would show it.

**Proposed fix.** Mirror the D/E guard: a negative denominator on `roe` /
`roa`, and a negative numerator-and-denominator pair on `ocf_to_net_income`,
become `Unavailable(AMBIGUOUS, "... not meaningful")`. One guard function in
`src/fincopilot/calc/ratios.py`, an amendment to spec §7.1, and about three
tests. Two existing hostile-fixture assertions would need updating.

**Not yet applied** because it changes approved behaviour and needs sign-off.

### 2. No plausibility check on any extracted number (MEDIUM)

`hostile.pdf` reports revenue of 999,999,999,999,999,999.00 crore. The
system accepts it, carries it exactly, and reports
`low_confidence_kpi: clear` because the row was matched deterministically
from a real page. `revenue_decline: clear` is likewise true — revenue went
up, absurdly.

This is defensible: confidence measures *how the row was identified*, not
whether the figure is believable, and inventing a magnitude ceiling risks
rejecting a legitimately large report. But no layer anywhere asks "is this
number sane relative to its siblings?"

**Options.** (a) Leave as is and document. (b) Add an INFO-level red flag
when a value is more than N orders of magnitude from the other values on the
same statement. (b) is new scope; it belongs in a Phase 9+ brainstorming
cycle, not a patch.

### 3. `types.py` is past its own review threshold (LOW)

610 lines against the ~600 line the plan set for revisiting the decision to
keep every contract in one file. It is still coherent — the types reference
each other constantly — but it should be reconsidered before Phase 9 adds
narrative types. A natural split is provenance/document types, analysis
output types, and the `Maybe`/`Unavailable` core.

### 4. Two verification gaps (LOW)

- **The live model test has never run.** `test_ollama_contract` is marked
  `@pytest.mark.ollama` and deselected by default and in CI. It needs a
  running Ollama with `qwen2.5:3b`. Everything around it is covered by a
  scripted fake, so the six rejection paths *are* tested; what is untested
  is whether a real `qwen2.5:3b` returns schema-valid JSON in practice.
  Run with `uv run pytest -m ollama`.
- **CI has never executed.** `.github/workflows/ci.yml` is committed but the
  repository has no remote, so GitHub Actions has never run it. The same
  sequence (`uv sync --dev`, `ruff check`, `ruff format --check`, `pytest`)
  passes locally.

---

## Resolved during this session

### `demo.py` printed a fabricated operator (was HIGH, fixed in `f5cd561`)

The demo joined a derived value's inputs with `" + "`, printing
`free_cash_flow = operating_cash_flow + capex` when free cash flow in fact
*subtracts* capex. The stored value was always correct (1,210 − 540 = 670);
only the printed label was wrong. Now prints
`derived from operating_cash_flow, capex` and names inputs without implying
an operation. Values also gained thousands separators and ratios are rounded
to four decimal places for display, leaving internal precision untouched.

---

## Accepted deviations - no action planned

These differ from the written plan on purpose. Each is recorded in the
fixture's expected-value file.

| Deviation | Reason |
|---|---|
| `hostile.pdf` uses an 18-digit value, not the planned 10^99 | A 100-digit token cannot render inside a 149-point table cell. It overflowed into the label column and the PDF reader merged the glyphs, destroying the row the test depends on. 18 digits is still far past the exactness of ordinary 64-bit numbers, which is what the case is for. |
| A mapped `capex` keeps the document's negative sign | The plan's expected file listed a positive magnitude, but the core invariant is that a mapped value must equal its source cell exactly. Spec §7.2 puts sign normalisation at free-cash-flow derivation, which is where it now happens. Spec won over plan. |
| `hostile.pdf`'s balance sheet balances | The plan asserted it would not. 5,100 − 820 = 4,280, so it does. The reconciliation *warning* path is covered by unit tests on constructed inputs instead. |
| Three-year income statements against two-year balance sheets | Not a deviation but worth restating: `golden_us.pdf` reproduces the real 10-K shape, which is why `PeriodMap` is keyed per statement and why 2022 ROA, ROE and total debt are correctly `unavailable`. |

---

## How to reproduce any of this

```bash
uv run python demo.py tests/fixtures/hostile.pdf
uv run python demo.py tests/fixtures/golden_indian.pdf
uv run python demo.py tests/fixtures/golden_us.pdf
```
