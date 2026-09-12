# Finance Copilot — Design Specification (Phases 0-8)

**Date:** 2026-09-12
**Status:** Approved
**Scope:** Phases 0-8 in full detail. Phases 9-13 intentionally high-level until Phase 8 review.
**Source:** Derived from `Finance_Copilot_Master_Build_Documentation.md` v1.0, refined through brainstorming. Where this document and the master documentation differ, **this document wins** — the differences are deliberate and are called out in §12.

---

## 1. Scope Decisions

These were decided during brainstorming and are binding.

| Decision | Value | Rationale |
|---|---|---|
| Report types supported | **Both** Indian (Ind-AS) and US (US-GAAP) annual reports | Two alias sets, two unit systems, two fixture families |
| Test PDFs | **Synthetic**, generated with ReportLab, committed to the repo | Real PDFs arrive at Phase 12; golden tests must be deterministic |
| Build scope this cycle | **Phases 0-8**, then stop for review | Phase 8 is the trust milestone: a working deterministic engine with no AI layer |
| Statement scope | **Consolidated only**; fall back to standalone and label loudly if no consolidated section exists | Matches analyst practice; the fallback keeps single-entity companies usable |
| LLM model | **Configurable**, default `qwen2.5:3b`, override via `.env` | Only `qwen2.5:1.5b` and `qwen2.5:3b` are installed locally; the Phase 5 task is narrow enough for 3b |
| Period handling | **Single document**, 2-3 periods taken from the statements themselves | No multi-document stacking, no 5-year highlights mining |
| Red-flag wording | Phrased as **year-over-year change**, not "trend" | Two periods is a change, not a trend; the product must not overclaim |
| EBITDA | **Derived** from `operating_income + d_and_a` when both map cleanly, else `Unavailable` | Neither convention line-items EBITDA; `d_and_a` is added to the canonical vocabulary |
| Repository | `git init` at `D:\Finance projects`, no remote yet; CI workflow committed regardless | Portfolio remote can be added later |
| Codex review (master doc §27) | **Aspirational.** Build so it can be reviewed; do not depend on it | No Codex access confirmed |

### 1.1 Accepted Risk

Synthetic fixtures are cleaner than real annual reports. Extraction that passes Phase 8 will very likely break on real PDFs at Phase 12. This is accepted knowingly. Mitigation: fixtures deliberately encode the known-hard cases (page-split statements, missing consolidated section, ambiguous periods, missing scale, hostile content) rather than an idealized happy path. **Fixture complexity must never be weakened to make extraction pass.**

---

## 2. Architecture

### 2.1 Repository Layout

```text
D:\Finance projects\
  app.py                    # Phase 10 — stub until then
  pipeline.py               # stage orchestration only
  src/fincopilot/
    types.py                # frozen dataclasses, closed-set enums, Maybe/Unavailable
    extract/
      pdf.py                # ingestion gate, page text, table extraction
      locate.py             # anchor scan + scored fallback + multi-page stitching
      periods.py            # column headers -> normalized periods
      units.py              # number grammars, scale resolution, currency
    mapping/
      synonyms.py           # deterministic label -> canonical concept
      validate.py           # claim validation: refs, scope, conflicts, invariants
    calc/
      ratios.py
      trends.py
    rules/
      redflags.py
    ai/
      client.py             # Ollama HTTP behind an injectable Protocol
      llm_map.py            # Phase 5 row-picker: schema, validation gate
  tests/
    fixtures/
      build_fixtures.py     # ReportLab generator (committed)
      *.pdf                 # generated PDFs (committed)
      expected/*.json       # hand-computed expected values (committed)
  docs/
  .github/workflows/ci.yml
```

`locate.py` is **not** folded into `pdf.py` as the master documentation implies. Statement location is the single most failure-prone step in the system and needs its own tests, its own error type, and its own scoring logic.

### 2.2 Module Boundaries — Non-Negotiable

**Dependency graph is strictly one-directional:**

```text
extract -> units -> mapping -> calc -> rules
```

No backwards imports. No module imports a module that runs later in the pipeline. This is what makes each stage independently testable and is enforced by review of every diff.

Additional boundary rules:

- `pipeline.py` is **orchestration only**. No Streamlit, no database, no direct Ollama calls, no financial logic.
- `app.py` (Phase 10) is **UI wiring only**. No financial business logic.
- All AI dependencies are **injected**. Phase 8 must run to completion with Ollama uninstalled.

### 2.3 Pipeline Contract

```text
bytes -> validate_input        -> DocumentRef
      -> extract_pdf           -> RawDocument
      -> locate_statements     -> StatementSet
      -> detect_periods        -> PeriodMap
      -> normalize_document    -> NormalizedTables
      -> map_financial_values  -> list[FinancialValue]
      -> validate_mappings     -> MappingReport
      -> calculate_metrics     -> MetricSet
      -> calculate_trends      -> TrendSet
      -> run_reconciliations   -> ReconciliationReport
      -> evaluate_red_flags    -> list[RedFlag]
      -> AnalysisResult
```

Every stage takes a contract in and returns a contract out, with no hidden state and **no hidden I/O after `extract_pdf`**. External I/O is permitted only through explicitly injected interfaces — in Phases 0-8 that means the LLM client and nothing else. Every deterministic stage remains a pure function. This is what makes the golden test possible: swap the injected client for `NullMapper` and the pipeline performs no I/O at all after extraction.

### 2.4 Core Invariants

1. **Numbers come only from the document.** `FinancialValue.normalized_value` can only be constructed by `units.py` from a `SourceRef` minted by `extract/`. There is no code path by which a model-produced number reaches a formula.
2. **No stage returns a plausible default.** Every stage that cannot do its job returns an explicit `Unavailable` carrying a reason.
3. **Provenance survives every transformation.** PDF -> cell -> `SourceRef` -> `NormalizedCell` -> `FinancialValue` -> `Metric` -> `RedFlag`. (Phase 9 extends this to `Insight`; through Phase 8 the chain ends at `RedFlag`.)

### 2.5 Validation Is Two Distinct Things

A naive reading creates a circular dependency: `units.py` (stage 5) cannot depend on `mapping/validate.py` (stage 8). The two validations are separate concerns:

- **Identity validation, at extraction time.** `extract/` is the *only* module that can mint a `SourceRef`. It is constructed while walking the extracted structure, so existence is true by construction and requires no later verification. `RawDocument` carries `refs: dict[str, SourceRef]` keyed by stable IDs of the form `page_12_table_1_row_4`.
- **Claim validation, at mapping time.** `mapping/validate.py` validates *claims*, not existence: an LLM returns the string `"page_12_table_1_row_4"`; validate looks it up in `refs`; a miss is a rejected mapping. It also detects conflicts and enforces cross-concept invariants.

`units.py` takes a `SourceRef` and returns a `NormalizedCell`. It performs no validation call and imports nothing from `mapping/`.

---

## 3. Domain Types and the Unavailable Contract

### 3.1 `Maybe` / `Unavailable`

"No guessed defaults" only holds if unavailability is a **type**, not a convention.

```python
class UnavailableReason(Enum):
    MISSING_INPUT = "missing_input"
    AMBIGUOUS = "ambiguous"
    CONFLICT = "conflict"
    UNPARSEABLE = "unparseable"
    NOT_LOCATED = "not_located"
    DIVISION_BY_ZERO = "division_by_zero"

@dataclass(frozen=True)
class Unavailable:
    reason: UnavailableReason
    detail: str
    refs: tuple[str, ...] = ()
    cause: "Unavailable | None" = None   # upstream failure, chainable

type Maybe[T] = T | Unavailable   # PEP 695 type alias, Python 3.12
```

Rules:

- **Never** use `None`, `0`, `NaN`, `inf`, or any sentinel number for unavailable financial data.
- Calculations **propagate** `Unavailable` rather than inventing values.
- `cause` chains so root causes stay visible. Example: `ROE = Unavailable(MISSING_INPUT, "equity unmapped", cause=Unavailable(NOT_LOCATED, "balance sheet not found on any page"))`. The UI walks to the root and reports the actionable fact.
- This must **not** be simplified into `None` handling for convenience. It is a core product correctness requirement, accepted with full knowledge that it adds unwrapping ceremony to nearly every calc function.

### 3.2 Confidence — Two Independent Axes

```python
class ExtractionConfidence(Enum):
    EXACT_MATCH = "exact_match"        # literal canonical label
    SYNONYM_MATCH = "synonym_match"    # curated alias hit
    LLM_MAPPED = "llm_mapped"          # model picked the row, Python took the number
    UNMAPPED = "unmapped"

class AnalyticalConfidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
```

The master documentation collapses the first two into `exact_match`. They are split here because a literal `"Revenue"` hit and a `"Total income from operations"` synonym hit are not the same strength of claim, and the UI must be able to show the difference.

`AnalyticalConfidence` is derived by rule from `ExtractionConfidence` plus reconciliation status. `LLM_MAPPED` caps analytical confidence at `MEDIUM` regardless of all other factors.

### 3.3 `SourceRef` and `FinancialValue`

```python
@dataclass(frozen=True)
class SourceRef:
    ref_id: str          # "page_143_table_1_row_7"
    document_id: str
    page: int            # TRUE page, preserved through stitching
    table_idx: int
    row_idx: int
    col_idx: int | None
    row_label: str
    raw_text: str
```

`FinancialValue` is frozen and carries the full master-doc §7 provenance set — `document_id`, `source_page`, `source_table`, `source_row`, `source_label`, `source_text`, `raw_value`, `normalized_value`, `unit`, `currency`, `period`, `extraction_confidence` — plus:

```python
derived_from: tuple[str, ...] | None = None
```

`derived_from` is populated for derived values (EBITDA, FCF, summed `total_debt`) so the provenance panel shows the formula and its inputs, not just a number.

### 3.4 `StatementSet.basis`

```python
class StatementBasis(Enum):
    CONSOLIDATED = "consolidated"
    STANDALONE_FALLBACK = "standalone_fallback"
    UNKNOWN = "unknown"
```

Decided by evidence, never assumption. When `UNKNOWN`, the pipeline **proceeds and labels** rather than blocking — refusing to analyze an unlabeled statement would kill every single-entity company. When `STANDALONE_FALLBACK`, the label is surfaced prominently at every level of output.

---

## 4. Extraction (Phase 2)

### 4.1 Ingestion Gate — `extract/pdf.py`

Ordered, cheapest rejection first:

1. **Size cap** — 50 MB default, configurable. Rejected before any parse.
2. **Magic bytes** — file must begin `%PDF-`. Browser MIME type is ignored entirely as a security boundary.
3. **`pdfplumber.open()`** inside a try. Encrypted or corrupt raises `UnreadablePDF`. A malicious xref table is handled here, by the try-block.
4. **Page cap** — 1000 pages. This is as early as the cap can possibly run: pdfplumber cannot report a page count without opening the document and letting pdfminer parse the xref. It lands before any text or table extraction, which is where the real cost is.
5. **Text-layer probe** — see §4.2.

Uploaded bytes stay in memory, or in an application-controlled temp path under the session scratchpad if disk is required. **The user's filename never touches the filesystem**; a UUID is used. Path traversal is structurally impossible because no user-supplied string is ever a path component. Uploaded content is never executed.

### 4.2 Text-Layer Probe — Heuristic, Not One Threshold

A single global character-count threshold is insufficient. The probe samples pages spread through the document and evaluates several signals:

- Total extracted character count across sampled pages.
- **Distribution**, not just total — a document where 3 pages carry all the text and 200 carry none is image-only with an OCR'd cover page.
- Per-page character density relative to page area.
- Presence of extractable words versus isolated glyphs or control characters.
- Whether any sampled page yields a table structure at all.

Sparse and pathological text layers are detected, not just fully empty ones. Failure raises `ScannedPDFUnsupported` explicitly. No OCR, no silent partial analysis.

### 4.3 Statement Location — `extract/locate.py`

Hybrid strategy, chosen over pure-anchor (brittle) and extract-everything (3-10 minutes per upload, unacceptable in Streamlit).

**Pass 1 — text-only, all pages.** `page.extract_text()` is roughly 10x cheaper than `extract_tables()`. Builds a page index recording per page: normalized text, heading-regex hits, numeric density.

Anchor patterns cover both conventions and track scope separately:

- Consolidated: `"Consolidated Balance Sheet"`, `"Consolidated Statement of Financial Position"`, `"Consolidated Statement of Profit and Loss"`, `"Consolidated Statements of Operations"`, `"Consolidated Statement of Cash Flows"`, and near variants.
- Standalone: the corresponding `"Standalone ..."` forms, plus unprefixed forms in single-entity reports.

**Pass 2 — table extraction on anchor-hit pages ±1 only.**

**Pass 3 — scored fallback**, for any statement still missing. Restricted to pages the text pass flagged as numeric-dense (typically 15-30 pages, not 300). Score = canonical-synonym label hits + numeric column count + row count. Below a minimum score, that statement becomes `Unavailable(NOT_LOCATED)` and **the pipeline continues with the other two statements** rather than dying.

**Scope scoring rule:** consolidated and standalone candidates are scored **separately**. A standalone candidate must **never** outrank a valid consolidated candidate. Consolidated is selected whenever a valid consolidated candidate exists, regardless of relative scores.

### 4.4 Multi-Page Stitching — First-Class Requirement

Statements routinely span two pages; pdfplumber returns them as separate tables with the header only on the first. Two tables are continuations when **all** hold:

- Consecutive pages.
- Matching column count.
- Approximately matching column x-positions.
- The second has no recognizable header row.

They merge into one logical table with the header inherited from the first. **Each row's `SourceRef` keeps its true page.** A row stitched from page 143 remains `page_143_table_1_row_7`. Provenance must survive stitching or the entire traceability claim is false.

---

## 5. Periods and Units (Phase 3)

### 5.1 Periods — `extract/periods.py`

Header cells are parsed for year patterns: `2024`, `FY2024`, `FY 2023-24`, `March 31, 2024`, `Year ended 31 March 2024`, `Fiscal 2024`.

- Indian fiscal years normalize to their **ending** year: `2023-24` -> `FY2024`. Original text is preserved.
- **Column order is decided by parsed years, never by position.** The first numeric column is never assumed to be the current year.
- Two columns parsing to the same period, or a header yielding no year, produces `Unavailable(AMBIGUOUS)` for the document. No guessing.

### 5.2 Scale Resolution — Hierarchical

Scale is resolved in order, and **where it was discovered is preserved** on the resulting values:

```text
cell -> table -> statement -> document
```

A cell-level scale marker beats a table caption; a table caption beats a statement-level note; that beats a document-level convention statement. Recognized phrases include `"(₹ in crore)"`, `"(Rs. in lakhs)"`, `"(₹ in million)"`, `"(in millions, except per share data)"`, `"(in thousands)"`, `"(₹ in '000)"`.

No scale found at any level -> `Unavailable(AMBIGUOUS)`. A bare `45,231` is meaningless.

### 5.3 Number Grammar — `extract/units.py`

Both grouping conventions are parsed by **explicit grammar**, never by heuristic guessing:

- **Western:** leading group of 1-3 digits, then groups of exactly 3.
- **Indian:** leading group of 1-2 digits, then groups of exactly 2, then a final group of exactly 3 (`12,34,567`).

If a string satisfies neither grammar, the result is `Unavailable(UNPARSEABLE)`. No best guess.

Also handled: parentheses negatives, trailing-minus negatives, explicit signs, currency symbols and codes, decimals, footnote markers glued to numbers.

### 5.4 Blank vs Dash — Decidable Rule

Blank and dash are **not** the same and conflating them corrupts reconciliation. The rule, committed to explicitly:

| Cell content (after stripping whitespace and any currency symbol) | Result |
|---|---|
| Exactly one of `-` `–` `—` `Nil` `NIL` `nil`, **and** the column is numeric (majority of other cells in that column parse as numbers) | **Zero**, `raw_token` preserved, `dash_zero=True` set on the cell |
| Empty or whitespace only | **Missing** |
| Dash plus other content (`"N/A —"`, `"—*"`, `"– see note 14"`) | **`Unavailable(UNPARSEABLE)`** |
| Column is not numeric | Dash is text, not a value |

The `dash_zero` flag is carried downstream. If reconciliation fails on a statement where dash-zeros were applied, the warning names them as a suspect. This is the honest form of "clearly an accounting zero": commit to the convention, mark where it was applied, let reconciliation catch it when wrong.

### 5.5 Currency

Detected per table. Two currencies within one statement -> `Unavailable(CONFLICT)`. **No FX conversion, ever.** Values normalize to a single internal base unit; the original scale and currency are retained for display.

---

## 6. Mapping (Phases 4-5)

### 6.1 Canonical Vocabulary

The master-doc §7 closed set, plus `d_and_a` (required for EBITDA derivation, omitted from the original list):

`revenue`, `gross_profit`, `cogs`, `operating_income`, `d_and_a`, `ebitda`, `net_income`, `total_assets`, `current_assets`, `cash`, `total_liabilities`, `current_liabilities`, `short_term_borrowings`, `long_term_borrowings`, `total_debt`, `equity`, `operating_cash_flow`, `capex`, `free_cash_flow`.

### 6.2 Deterministic Pass — `mapping/synonyms.py`

Runs **first, always.** Label normalization strips case, punctuation, footnote markers, trailing colons, leading numbering, and collapses whitespace. Then:

- **Tier 1, exact canonical** — normalized label is in the canonical alias table -> `EXACT_MATCH`.
- **Tier 2, curated synonym** — hits a per-jurisdiction alias set -> `SYNONYM_MATCH`.

**No fuzzy matching, edit distance, embeddings, or semantic matching anywhere in Tier 1 or Tier 2.** Every alias is an explicit curated string. Fuzzy matching is precisely how these tools produce confidently wrong numbers.

**Negative lists are mandatory and as important as positive ones.** Known semantic traps that must be blocked:

- Indian `"Total income"` must **not** map to `revenue` — it includes other income, and mapping it is the most common way these tools silently overstate a topline. Correct source is `"Revenue from operations"`.
- `"Total current liabilities"` must never match `total_liabilities`.
- `"Cash and cash equivalents at end of period"` (cash flow statement) must not compete with the balance-sheet `cash` row.

**Structural constraints on top of label matching:**

- A concept may only be sourced from its expected statement (`revenue` only from the income statement, `total_assets` only from the balance sheet).
- A row labeled only `"Total"` resolves by its **section header**, never by the word alone.

### 6.3 LLM Fallback — `ai/llm_map.py` (Phase 5)

Runs **only** for concepts still unmapped after Tier 2.

**Prompt input:** the target concept and its plain-English definition, plus a candidate list of unmapped rows **from the correct statement and selected statement scope only** — label and row ID, capped at ~40 rows.

**The model never receives financial numbers.** Not the table, not the page, not the values. Nothing it returns can be a number because it never saw one.

**Response constrained** by Ollama's JSON-schema `format` parameter, `temperature=0`, fixed seed:

```json
{"source_row_id": "page_12_table_1_row_4", "confidence": "high", "reasoning": "..."}
```

`{"source_row_id": null}` is a **mandatory** explicit decline option. Without it, a small model always picks something.

**Validation gate — every path rejects, none repairs:**

1. Response is not valid JSON -> reject.
2. Response does not match schema -> reject.
3. `source_row_id` not present in `RawDocument.refs` -> reject (catches hallucinated IDs).
4. Ref exists but belongs to a different statement or scope than the concept requires -> reject.
5. Ref's row is already mapped to another concept -> `CONFLICT`.
6. Response contains any numeric field beyond the schema -> reject **and log as a contract violation**.

Surviving all six: **Python** retrieves the row from `refs`, pulls the numeric cell for each period, and runs it through `units.py`. Extraction confidence is `LLM_MAPPED`, which caps analytical confidence at `MEDIUM`.

**Failure isolation:** Ollama unreachable, timing out (10s), or returning garbage leaves the concept `UNMAPPED` and the pipeline continues. The deterministic path never waits on or depends on the model.

### 6.4 Claim Validation — `mapping/validate.py`

Document-level checks after mapping:

- Exactly one value per concept × period; duplicates are `CONFLICT`.
- All refs resolve within this document.
- No concept sourced from a statement it cannot come from.
- `total_debt` does not double-count when `short_term_borrowings` and `long_term_borrowings` are also mapped (see §7.2).

---

## 7. Calculations, Reconciliation, Red Flags (Phases 6-7)

### 7.1 `calc/ratios.py`

Pure functions over mapped values, each returning `Maybe[Metric]`. All master-doc §12 formulas, with these guards:

- **`decimal.Decimal` end to end**, quantized only at display. Crore-scale values in float64 accumulate error that surfaces in reconciliation as phantom mismatches.
- **Zero or unavailable denominator** -> `Unavailable(DIVISION_BY_ZERO)` with the denominator's ref in `refs`. Never `inf`, never `NaN`.
- **Negative equity** -> D/E is `Unavailable(AMBIGUOUS, "equity is negative; ratio not meaningful")`. A distressed company would otherwise display a tidy negative D/E that reads as *low* leverage. This is an analytical trap, not a math one.
- **Zero or negative revenue** -> all margin metrics `Unavailable`.
- **ROA / ROE** require two periods of the balance-sheet denominator for the average. One period -> `Unavailable(MISSING_INPUT, "prior-period total assets required for average")`. Never substitute a single period.

### 7.2 Derived Values — Strict Pattern

All three follow the same shape:

| Value | Resolution order |
|---|---|
| `total_debt` | Directly mapped row wins. Otherwise `short_term_borrowings + long_term_borrowings` **only when both exist**, `derived_from` populated. One present and one absent -> `Unavailable(MISSING_INPUT)`, never a half-sum. |
| `free_cash_flow` | Mapped row wins. Otherwise `operating_cash_flow - capex`, capex normalized to positive magnitude first, `derived_from` populated. |
| `ebitda` | Mapped row wins. Otherwise `operating_income + d_and_a` when both map cleanly, `derived_from` populated and flagged as derived in the UI. Otherwise `Unavailable`. Never fabricated. |

### 7.3 `calc/trends.py`

YoY between **adjacent periods only**. Direction is computed in Python and carries economic sense: rising `total_debt` is `direction=up, economic=negative`; rising `revenue` is `up, positive`. The Phase 9 narrative model receives these labels and never derives them itself, so it cannot describe rising leverage as "strong balance-sheet growth."

### 7.4 Reconciliation — Soft Checks

| Check | Tolerance |
|---|---|
| Assets ≈ Liabilities + Equity | 0.5% of total assets |
| Gross Profit ≈ Revenue − COGS | 0.5% of revenue |
| FCF = OCF − Capex | exact (we compute it) |

- Within tolerance -> `passed`.
- Outside tolerance, inputs present -> `warning`, showing both sides and the delta.
- Inputs missing -> `unavailable`.

**No hard failures.** Presentation rounding in a crore-denominated report routinely produces sub-1% gaps; a brittle equality check would fire on nearly every real report.

### 7.5 Red Flags — `rules/redflags.py`

Each rule is a dataclass carrying an ID, a predicate, a severity, the refs it fired on, and a plain-English template. **The rule decides whether it fires. The LLM may later explain a rule that already fired; it never decides that a rule fired.**

| Rule | Fires when |
|---|---|
| `revenue_decline` | revenue YoY < 0 |
| `margin_compression` | gross or operating margin down > 200 bps YoY |
| `leverage_increase` | D/E increase > 0.25 absolute **AND** D/E > 1.0 |
| `high_leverage` | D/E > 2.0 |
| `negative_fcf` | FCF < 0 |
| `negative_ocf` | OCF < 0 |
| `weak_liquidity` | current ratio < 1.0 |
| `earnings_quality` | OCF / net income < 0.7, both positive |
| `reconciliation_warning` | any reconciliation in `warning` |
| `low_confidence_kpi` | revenue or net income is `LLM_MAPPED` or `UNMAPPED` |

Rules whose inputs are `Unavailable` **do not fire and do not silently pass** — they report `not_evaluated` with the reason, so the UI can distinguish "checked, clean" from "couldn't check."

**Thresholds are editorial MVP defaults**, declared in a single documented constants block at the top of `redflags.py`, not scattered through predicates, so they remain configurable later. Two are explicitly acknowledged as judgment calls: `earnings_quality` at 0.7 is a conventional but arbitrary screen; `leverage_increase` requiring both a delta and an absolute floor deliberately suppresses a 0.1 -> 0.4 D/E move.

---

## 8. Fixtures

The ReportLab generator **and** the generated PDFs are both committed. **PDFs are never regenerated during tests** — a fixture that regenerates differently under a new ReportLab version silently invalidates the golden test. Generation is deterministic (fixed seeds, no timestamps, no environment-dependent content).

| Fixture | Exercises |
|---|---|
| `golden_indian.pdf` | Ind-AS, ₹ crore, 2 periods, consolidated **and** standalone both present, statements on pages 40-46 of ~60, narrative filler surrounding them |
| `golden_us.pdf` | US-GAAP, $ millions, 3 periods, consolidated only |
| `stitched.pdf` | Balance sheet split across two pages, header on the first only |
| `standalone_only.pdf` | No consolidated section — proves the labeled fallback |
| `ambiguous_periods.pdf` | Two columns parsing to the same year |
| `no_scale.pdf` | No scale phrase anywhere |
| `scanned.pdf` | Image-only, no text layer |
| `hostile.pdf` | Prompt injection in the narrative, 10^99 values, a 500-row table, mixed dashes and blanks, a negative-equity balance sheet |

**Expected values are hand-computed independently and written down before the implementation exists.** That is what makes this a golden test rather than a snapshot of whatever the code happened to produce.

---

## 9. Testing

- **Unit tests** per module: number grammars, scale resolution, period detection, dash/blank rule, synonym and negative-list mapping, ref validation, each formula, each guard, each trend, each reconciliation, each red-flag rule (firing and not firing).
- **Integration tests** at every stage boundary.
- **Adversarial tests**: the `hostile.pdf` battery, oversized file, bad magic bytes, encrypted PDF, path-traversal filenames, prompt injection, division by zero, extreme and NaN-adjacent values, missing periods.
- **LLM contract tests**: all six rejection paths from §6.3.

**Three golden tests:**

| Test | LLM client | In CI |
|---|---|---|
| `test_golden_deterministic` | `NullMapper` (always declines) | **Yes** — must pass with no Ollama installed |
| `test_golden_with_fallback` | Scripted fake returning canned row IDs, including an invalid one | **Yes** |
| `test_ollama_contract` | Real model | **No** — marked `@pytest.mark.ollama`, deselected |

CI runs the first two only. GitHub Actions has no Ollama.

TDD per master-doc §26: tests are written before the implementation they cover, and committed alongside it.

---

## 10. Phase Breakdown and Verification Gates

| Phase | Deliverable | Verification gate |
|---|---|---|
| **0** | `uv init`, `git init`, pyproject, Ruff config, pytest config, CI workflow, `.gitignore`, `.env.example` | Empty suite green in CI |
| **1** | `types.py` complete (`Maybe`, `Unavailable`, `SourceRef`, `FinancialValue`, both confidence enums, all stage contracts). Fixture generator, all eight PDFs, expected-value JSON | Types tested; fixtures open in a reader; expected values written before any extraction code |
| **2** | `pdf.py` gate + extraction; `locate.py` anchor / fallback / stitch | Statements located in both goldens; stitched fixture merges with true page refs preserved; scanned fixture rejected; standalone-only fixture labels correctly |
| **3** | `periods.py`, `units.py` | Both number grammars; all scale phrases; hierarchical scale resolution; dash/blank rule; ambiguous fixtures return `Unavailable` |
| **4** | `synonyms.py`, both alias sets, negative lists | Every concept in both goldens maps at `EXACT_MATCH` / `SYNONYM_MATCH`; `"Total income"` does not become `revenue` |
| **5** | `ai/client.py` Protocol + Ollama impl, `llm_map.py`, `mapping/validate.py` | All six rejection paths; unreachable-Ollama path leaves pipeline intact |
| **6** | `ratios.py`, `trends.py` | Every formula, every guard, Decimal precision at crore scale |
| **7** | Reconciliation, `redflags.py` | Each rule fires and does not fire on constructed inputs; `not_evaluated` propagates with reason |
| **8** | `pipeline.py` wiring all stages | See §10.1 |

### 10.1 Phase 8 Definition of Done

- Both golden PDFs produce **every** expected value, compared as **`Decimal` at full internal precision**. Golden tests assert the internal `Decimal` values *before* any presentation formatting. Display-rounded values are never the subject of a golden assertion.
- The **complete provenance chain** is asserted end to end: PDF -> cell -> `SourceRef` -> `NormalizedCell` -> `FinancialValue` -> `Metric` -> `RedFlag`.
- **Zero fabricated values** — proven, not assumed.
- The full pipeline **runs to completion with Ollama uninstalled**.
- Ruff clean (`check` and `format --check`). CI green.

**Commit cadence:** minimum one commit per phase, with tests committed alongside the implementation they cover.

---

## 11. Phases 9-13 — High Level Only

Deliberately not detailed. Each gets its own brainstorming cycle after Phase 8 review.

- **Phase 9 — Grounded narrative.** Ollama behind the injectable client. The model receives structured metrics, trends, red flags, reconciliation statuses, and selected source evidence — never the raw PDF. It must not calculate, invent values, invent causes, or hide uncertainty. Validation failure or Ollama absence leaves the deterministic analysis fully intact.
- **Phase 10 — Streamlit dashboard.** UI wiring only in `app.py`. KPI cards, trends, reconciliation, red flags, provenance panel. N/A, warning, and low-confidence values must be visually distinct from verified results.
- **Phase 11 — SQLite persistence.** Deliberately thin: `documents`, `financial_values`, `calculated_metrics`, `insights`, `questions`. Never a second copy of the PDF.
- **Phase 12 — Real annual-report validation.** The phase where synthetic-fixture optimism meets reality. Expect extraction rework.
- **Phase 13 — README, screenshots, security review, polish.**

Document Q&A (master-doc §16) is P1 and out of scope for this cycle.

---

## 12. Deliberate Divergences from the Master Documentation

| Master doc | This spec | Why |
|---|---|---|
| §5 folds statement location into `extract/pdf.py` | Separate `extract/locate.py` | Highest-risk step; needs isolated tests and its own error type |
| §7 vocabulary omits `d_and_a` | `d_and_a` added | Required for EBITDA derivation, which §12 permits |
| §7 extraction confidence: `exact_match` | Split into `exact_match` / `synonym_match` | Different strengths of claim; UI must distinguish |
| §19 pipeline has no location stage | `locate_statements` added between `extract_pdf` and `detect_periods` | Location is a real stage with a real contract |
| §20 implies `None`-style missing values | Typed `Unavailable` with reason and causal chain | "Never guess" is only enforceable as a type |
| §23 Phase 8 "without the AI layer" | Three golden tests, since Phase 5 (LLM fallback) sits inside 0-8 | One test cannot cover both the deterministic-only and fallback paths |
| §27 Codex as reviewer | Treated as aspirational | No confirmed Codex access |

---

## 13. Security Posture (Phases 0-8)

- Uploaded PDFs are hostile input. Size and magic-byte validation precede parsing. Uploads are never executed.
- User filenames never become filesystem paths. UUIDs are used. Path traversal is structurally impossible.
- All document text is untrusted prompt content. Prompt injection inside an uploaded report must never override application instructions — enforced structurally: the Phase 5 model sees only row labels and IDs, and its response is constrained to a schema whose every field is validated against extracted data.
- **LLM output can never become a financial number.** Enforced by the type system, not by convention.
- `.env` is gitignored; `.env.example` is committed. No secrets in source control.
- Logs never leak secrets or document contents.

---

## 14. Final Principle

Through Phase 8, the chain is:

```text
PDF -> source row -> normalized value -> formula -> metric -> red flag
```

Phase 9 extends it one link further, to narrative insight, by requiring the narrative to cite the metric and red-flag IDs it discusses. Through Phase 8 there is no insight link, and Phase 8's definition of done must not be read as requiring one.

Every conclusion the product states must be explainable along that chain. Build the deterministic engine first, prove the numbers, preserve provenance, then add AI for interpretation only.
