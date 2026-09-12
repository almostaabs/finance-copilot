# Finance Copilot

A local tool that reads a company's annual report (PDF) and produces a
trustworthy financial analysis: the key numbers, the ratios, how they changed
year over year, whether the books add up, and a list of warning signs.
Every number it shows can be traced back to the exact row on the exact page
of the PDF it came from. Nothing is guessed, and no AI ever supplies a number.

**Status:** Phases 0-8 complete (the deterministic engine). No user interface
yet; that is Phase 10. Runs entirely on your machine. No data leaves it.

---

## What it does, in one paragraph

You give it a PDF. It checks the file is safe to open, finds the three
financial statements inside (profit and loss, balance sheet, cash flow),
works out which columns are which years and what units the report uses
(crore, millions, and so on), reads the numbers, matches each row to a
standard concept such as "revenue" or "total debt", computes ratios, checks
the statements against each other, runs ten warning-sign rules, and returns
a result where every figure carries its source and every missing figure
carries a reason for being missing.

## What makes it different

Most tools that "read financial PDFs with AI" quietly make things up when the
document is unclear. This one is built on four rules:

1. **Numbers come only from the document.** Code physically cannot construct
   a financial value without a pointer to the PDF cell it came from.
2. **Nothing is guessed.** When something cannot be determined, the result
   is an explicit "unavailable" with a reason (missing input, ambiguous,
   conflicting, unparseable, not located, division by zero) and a chain
   back to the original cause.
3. **The AI is optional and narrow.** A small local model may be asked
   *which row* means "gross profit" when the deterministic matcher gives
   up. It only ever sees row labels, never numbers, and its answer is
   checked six ways before being accepted. Turn it off and everything still
   works.
4. **Provenance survives every step.** PDF page -> cell -> normalised number
   -> named concept -> ratio -> warning sign. A warning can always be
   explained back to the printed figures that triggered it.

## What you get back

| Output | Example |
|---|---|
| Values | `revenue 2024 = 12,450.00 crore` from page 41, row "Revenue from operations", matched by curated synonym |
| Derived values | `ebitda = operating_income + d_and_a`, with both inputs named |
| Ratios | gross/operating/net/EBITDA margin, current ratio, debt-to-equity, ROA, ROE, cash-flow-to-profit |
| Trends | year-over-year change, with direction *and* whether that is good or bad for the business (rising debt is "up" and "negative") |
| Reconciliations | assets = liabilities + equity, gross profit = revenue - cost of sales, FCF = operating cash flow - capex; each *passed*, *warning*, or *unavailable* |
| Red flags | ten rules (revenue decline, margin compression, high leverage, negative cash flow, weak liquidity, weak earnings quality, ...). Each is *fired*, *clear*, or *not evaluated* with the reason. "Checked and fine" is never confused with "could not check". |
| Basis label | *consolidated*, *standalone (fallback)*, or *unknown*, surfaced at the top so a fallback is never silent |

## Supported reports

Indian (Ind-AS, rupees in crore/lakh, "FY 2023-24" style years) and US
(US-GAAP, dollars in millions, three years of operations against two
balance sheets). Both are covered by "golden" test reports with hand-checked
answers.

## Running it

```bash
uv sync --dev
uv run pytest          # 297 tests, no AI needed
uv run ruff check .
```

See it work on a bundled test report:

```bash
uv run python demo.py                      # or: uv run python demo.py your_report.pdf
```

From Python:

```python
import pipeline

result = pipeline.analyze(open("report.pdf", "rb").read())  # deterministic only
result = pipeline.analyze(data, llm=OllamaClient.from_env())  # with optional local AI
```

Optional AI fallback needs [Ollama](https://ollama.com) with `qwen2.5:3b`
(configurable in `.env`, see `.env.example`). The live-model test is
excluded from the normal run and from CI.

## Limits, stated plainly

- Tested on synthetic PDFs that deliberately include the hard cases
  (page-split tables, missing consolidated section, ambiguous years, no units
  stated, hostile content). Real-world annual reports (Phase 12) will surface
  extraction gaps; that is expected and planned for.
- Scanned (image-only) PDFs are rejected. No OCR.
- No currency conversion, ever. Values stay in the report's currency.
- Two-period documents give a year-over-year *change*, deliberately not
  called a "trend".

## Where things live

```
demo.py                      run an analysis and print it, to see the output
pipeline.py                  the stages, in order, and nothing else
src/fincopilot/types.py      every data contract (the vocabulary of the system)
src/fincopilot/extract/      PDF gate, statement finding, periods, units
src/fincopilot/mapping/      row label -> concept, and claim validation
src/fincopilot/ai/           optional local-model row picker
src/fincopilot/calc/         derived values, ratios, trends, reconciliation
src/fincopilot/rules/        red-flag rules and their thresholds
tests/fixtures/              the eight generated PDFs and the hand-computed answers
docs/superpowers/specs/      the approved design (source of truth)
docs/HOW_IT_WAS_BUILT.md     how it was built and how it works, step by step
```

## Roadmap

Phase 9 grounded AI narrative (explains the numbers, cites them, never
computes) - Phase 10 Streamlit dashboard - Phase 11 SQLite persistence -
Phase 12 validation on real annual reports - Phase 13 polish and README
screenshots.
