# How Finance Copilot Was Built, and How It Works

Written for a reader with no programming background who needs to explain the
system accurately to engineers. Short on purpose.

---

## Part 1 - How it was built

### The order of work

1. **Design first, code second.** A written specification was agreed line by
   line before any code existed (`docs/superpowers/specs/...design.md`). It
   is the contract; the code follows it, not the other way round.
2. **Answers before the machine.** Eight test PDFs were generated with fixed
   content, and the correct answers for each were worked out by hand and
   saved as files *before* the code that reads PDFs was written. That way the
   tests check the code against independent truth, not against whatever the
   code happened to produce.
3. **Tests before code, every time.** For each feature the failing test was
   written first, then the smallest code that makes it pass. 297 automated
   tests existed at Phase 8; 394 exist now. All pass. A lint tool (Ruff) enforces style.
4. **One phase, one commit.** Fourteen phases (0-13), each committed with its tests.

### Phases 0-8: the deterministic engine

| Phase | Built | Proven by |
|---|---|---|
| 0 | Project skeleton, automated checks (CI) | empty test suite runs green |
| 1 | The vocabulary: every data shape the system uses; the eight test PDFs; hand-computed answers | types tested; PDFs open; file hashes pinned so nobody can silently change the answers |
| 2 | Safe PDF opening; finding the three statements; joining tables split across pages | statements found in both golden reports; split table rejoined with correct page numbers; scanned PDF rejected |
| 3 | Reading years from column headers; reading numbers in Indian and Western formats; working out units and currency | both grammars; every unit phrase; dash-vs-blank rule; ambiguous reports refused |
| 4 | Matching row labels to standard concepts | every concept in both golden reports matched; known traps blocked |
| 5 | Optional local AI as a last-resort row picker, with a strict gate | all six rejection paths; AI switched off leaves everything intact |
| 6 | Derived figures, ratios, year-over-year changes | every formula, every guard, exact decimal arithmetic |
| 7 | Cross-checks between statements; ten red-flag rules | each rule fires and stays quiet on constructed inputs |
| 8 | Wiring it all together; golden end-to-end tests | every expected number reproduced exactly; full provenance chain verified; runs with no AI installed |

### Phases 9-13: narrative, dashboard, history, real reports, polish

| Phase | Built | Proven by |
|---|---|---|
| 9 | Plain-English reading written by the optional local model from a structured summary of the results, never the PDF. Every sentence must cite result IDs that exist and every number must be one the model was shown; one fabricated figure rejects the whole thing. Markdown and HTML refused. | 24 gate tests: bad JSON, unknown cites, invented numbers, markup, nesting bombs, a dead model |
| 10 | The dashboard (`app.py`): upload, KPI cards, seven tabs, provenance viewer, optional narrative. Verified, low-confidence, and unavailable values render distinctly. `app.py` only formats and lays out; every row it shows is built by `views.py`, which is pure and tested. | rendered headless on the golden, hostile, and ambiguous-period fixtures |
| 11 | Local SQLite history: five thin tables, results only, never the PDF, values stored as exact decimal text | round-trip, cascade delete, path-stripped names, corrupt file |
| 12 | Three real annual reports (Apple, Berkshire, Wipro) went from zero values to a coherent set each. Statements printed without ruling lines are now rebuilt from word positions; text with no spaces is re-read; page-split statements rejoin; a report that prints two sets of statements yields one coherent set. | `text_aligned.pdf`, a ninth fixture encoding every real-report case; `docs/PHASE12_VALIDATION.md` |
| 13 | README, screenshots, security review, a stress pass over the new code with every finding fixed | this document, `docs/SECURITY_REVIEW.md`, `docs/KNOWN_ISSUES.md` |

### The test reports

| PDF | Why it exists |
|---|---|
| `golden_indian.pdf` | 60 pages, rupees in crore, two years, consolidated *and* standalone sections with different numbers so picking the wrong one fails loudly |
| `golden_us.pdf` | 34 pages, dollars in millions, three years of operations but only two balance sheets, the real 10-K shape |
| `stitched.pdf` | balance sheet cut across two pages, header on the first only |
| `standalone_only.pdf` | no consolidated section anywhere; must fall back and say so |
| `ambiguous_periods.pdf` | two columns that both mean 2024; must refuse, not guess |
| `no_scale.pdf` | never says crore or millions; a bare number is meaningless |
| `scanned.pdf` | picture only, no text; must be rejected |
| `hostile.pdf` | prompt-injection text, an 18-digit value, dashes vs blanks, unparseable cells, negative equity, a 500-row table |
| `text_aligned.pdf` | no ruling lines anywhere, `$` signs, a Notes column, a continuation page that repeats the heading, a year-less convenience column |

The PDFs are committed and their fingerprints pinned. Tests never regenerate
them, so the ground truth cannot drift.

---

## Part 2 - How it works

Think of a factory line with eleven stations, then a display window and a filing cabinet. Each station takes one
well-defined thing in and hands one well-defined thing out. No station keeps
secrets, and after station 2 none of them touches the outside world (except
station 6, only when the optional AI is switched on).

```
PDF bytes
 1  validate_input      file size cap, must begin with "%PDF-"; gets an anonymous ID
 2  extract_pdf         open safely, cap 1000 pages, check there is real text,
                        read every page's text, read tables only on promising pages
 3  locate_statements   find P&L, balance sheet, cash flow; consolidated beats
                        standalone; rejoin page-split tables
 4  detect_periods      column headers -> years, per statement
 5  normalize_document  every cell -> exact decimal in base units, with units/currency
 6  map + LLM fallback  row label -> concept (curated lists); AI asked only for leftovers
 7  validate_mappings   one row per concept, right statement, real row, pull the number
 8  calculate_metrics   derived values and ratios
 9  calculate_trends    year-over-year changes with good/bad sense
10  run_reconciliations do the statements agree with each other
11  evaluate_red_flags  ten rules
AnalysisResult
```

### Station by station, in plain terms

**1-2 The gate.** Cheapest checks first: too big, wrong file type, corrupt,
too many pages, no readable text. Uploaded content is never run or saved
under its own name. A scanned image gets an explicit "unsupported", not a
half-answer.

**3 Finding the statements.** The text of every page is scanned for headings
such as "Consolidated Balance Sheet". Tables are then read only on those
pages and on pages dense with numbers, which keeps a 300-page report fast.
Consolidated and standalone candidates are scored separately; a standalone
table can never beat a consolidated one. If no consolidated section exists,
the standalone one is used and the whole result is labelled
"standalone fallback". A table cut across two pages is rejoined, but every
row remembers the page it was actually printed on.

**4 Years.** Column headers become years by parsing, never by position:
"FY 2023-24" means 2024; "As at 31 March 2023" means 2023. If two columns
mean the same year, or a header has no year, the document is declared
ambiguous and no numbers are produced.

**5 Numbers, units, currency.** Two number grammars are recognised
explicitly: Western `12,450.00` and Indian `12,34,567`. Anything matching
neither is "unparseable". Brackets and trailing minus mean negative. A lone
dash in a numeric column is zero and is *flagged* as such; a blank is
missing; a dash with other text is unparseable. Units are resolved from the
most specific place they are stated (cell, then table caption, then
statement page, then document cover) and where they were found is recorded.
No units anywhere means no numbers.

**6 Matching labels to concepts.** Nineteen standard concepts (revenue,
cost of sales, operating income, depreciation, net income, total assets,
cash, equity, borrowings, operating cash flow, capex, ...). Matching uses
exact curated strings only: first the canonical label, then known synonyms
for Indian and US reports. No "close enough" matching, because that is how
tools produce confident wrong numbers. Negative lists block known traps: an
Indian "Total income" is never revenue (it includes other income); "Total
current liabilities" is never "total liabilities"; a cash-flow "cash at end
of year" is never balance-sheet cash. Each concept may only come from its own
statement.

**6b The optional AI.** Only for concepts still unmatched. The local model
receives the concept's definition and a list of up to 40 row labels with
their IDs. It never sees a number. It answers with one row ID or "none". The
answer is rejected if it is not valid JSON, breaks the schema, names a row
that does not exist, names a row from the wrong statement, names a row
already used, or contains any numeric field. Nothing is repaired. If the
model is unreachable or slow, the concept simply stays unmatched. Accepted
picks are marked "AI-mapped" and their confidence is capped at medium.

**7 Validation.** One row per concept; duplicates become a conflict rather
than a choice. Then Python, not the model, reads the number from the row.

**8 Ratios.** Total debt, free cash flow and EBITDA are derived only when a
directly printed row is absent *and* every input is present; half-sums are
never made. Ratios use exact decimal arithmetic at 34 significant digits.
Guards: dividing by zero gives "unavailable", never infinity; negative equity
makes debt-to-equity "not meaningful"; zero or negative revenue disables
margins; return on assets/equity needs two balance sheets and never
substitutes one.

**9 Trends.** Adjacent years only. Direction (up/down/flat) and economic
sense (good/bad) are assigned by code, so rising debt is "up, negative" and
nothing downstream can call it growth.

**10 Reconciliation.** Three checks with a 0.5% tolerance for the two that
depend on printed rounding. Outcomes are passed, warning, or unavailable.
Never a hard failure. A warning names any dash-zero cells as suspects.

**11 Red flags.** Ten rules, thresholds kept in one documented block. Each
reports fired, clear, or not evaluated with the reason. The rule decides;
an AI may later explain a fired rule but never decide one.

**After the line.** The dashboard (`app.py`) only formats what the line produced. The
history file (`store.py`) keeps the results, not the PDF. The optional narrative
(`ai/narrative.py`) is written last, from the finished results, and is thrown away
whole if it cites anything that does not exist or states a number it was not shown.

### The one idea to remember

"Unavailable" is a type, not a blank. Every missing figure carries a reason
and a chain back to the first thing that went wrong, so the answer to "why is
ROE blank?" is "because equity was not matched, because the balance sheet was
not found on any page", not a shrug. And every figure that *is* shown can be
walked back to a printed cell on a numbered page. Those two properties are
what the 394 tests exist to protect.
