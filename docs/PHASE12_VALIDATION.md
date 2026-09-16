# Phase 12: real annual-report validation

Three public annual reports were run through the pipeline on 2026-09-12. The PDFs are
**not** committed (they are the publishers' documents, and they are large); they were
downloaded to a scratch directory and run with `uv run python demo.py <path>`. Anyone can
repeat this with the same files: `tests/fixtures/real/README.md` lists where to download
each one, and `tests/fixtures/real/run_all.py` is the harness that runs the set.

| Report | Pages | Format | Before rework | After rework |
|---|---|---|---|---|
| Apple 10-K FY2023 | 80 | US GAAP, whitespace-aligned statements | periods unavailable, 0 values | 3 periods, 14 concepts, every reconciliation passes |
| Berkshire Hathaway 10-K 2023 | 152 | US GAAP, glyphs so tight that text had no spaces | periods unavailable, 0 values | 3 periods, 5 concepts, 1 red flag fired |
| Wipro Integrated Annual Report FY24 | 481 | Ind AS + IFRS sets, Notes column | wrong tables (a deferred-tax note), periods unavailable | 2 periods, 10 concepts, balance sheet ties out |

## Second pass, 2026-09-13: five reports

Two more were added from company-hosted PDFs (aggregator sites rate-limit automated
downloads). None are committed. Run any of them with `uv run python demo.py <path>`.

| Report | Time | Basis found | Concepts | Notable |
|---|---|---|---|---|
| Apple 10-K FY2023 | 12s | consolidated | 13/19 | revenue decline and weak liquidity both fire, and both are true |
| Berkshire 10-K 2023 | 44s | consolidated | 5/19 | cash claimed by two segment rows, reported as a conflict |
| Microsoft 10-K FY2024 | 16s | **standalone fallback** | 14/19 | see the open question below |
| Merchants Bancorp 10-K 2024 | 27s | consolidated | 5/19 | a bank: no classified balance sheet exists |
| Wipro FY24 | 98s | consolidated | 10/19 | Ind AS and IFRS sets, one coherent group chosen |

### One bug, found and fixed

A truncated download parses as a valid PDF carrying **zero pages**. `_probe_text_layer`
indexed into the empty page list and raised `IndexError`, escaping the ingestion gate as an
unhandled crash. It now raises `UnreadablePDF`. Regression:
`test_a_pdf_with_no_pages_is_refused_not_a_crash`. A separate truncated file was already
handled correctly as `UnreadablePDF`.

### Correct behaviour that looks like low coverage

Banks (Merchants Bancorp, and Berkshire's insurance operations) do not publish a classified
balance sheet, so current assets, current liabilities and therefore the current ratio do not
exist in the document. Reporting them unavailable is right; inventing them would not be. The
same applies to gross profit at a bank. Coverage numbers for financial institutions should be
read against what the statement actually contains, not against all 19 concepts.

### Open question: unprefixed statements in a 10-K

Microsoft titles its primary statements "INCOME STATEMENTS" and "BALANCE SHEETS" with no
"Consolidated" prefix, so the unprefixed rule labels the whole analysis **standalone
fallback**. For a 10-K this is misleading: the primary statements in a 10-K are consolidated
by law. The rule is doing what spec 4.3 says and is labelling loudly rather than guessing, so
this is flagged, not silently changed. A fix would treat a US filing's unprefixed primary
statements as consolidated, which needs a spec amendment.

## What broke, and what was changed

Every item below is deterministic, covered by `tests/test_extract_textgrid.py` and
`tests/test_extract_locate.py`, and reproduced by the committed fixture `text_aligned.pdf`.

1. **Statements printed without ruling lines** (all three reports). pdfplumber's lattice
   finder returned one-column rows. Added `extract/textgrid.py`: value tokens are right-aligned,
   so their right edges cluster into columns; the header is the nearest line above the first
   data row whose year tokens map onto those columns. Used only when a page has no ruled table
   with a period-bearing header, so the synthetic fixtures are extracted exactly as before.
2. **Text with no spaces** (Berkshire). One document-wide re-read with `x_tolerance=1.5` when
   the space-to-character ratio is under 0.08.
3. **"Statements of Earnings"** (Berkshire) added as an income-statement anchor.
4. **Notes column** (Wipro). A numeric column with no year over it and only small plain integers
   is dropped. A numeric column with no year over it at all (Wipro's US$ convenience translation)
   is dropped when at least two year columns exist, instead of making every period ambiguous.
5. **Continuation pages that repeat the heading and header** (all three). Stitching now accepts
   an identical header, looks past an unrelated table on the same page, ignores the label
   column's left edge (indentation moves it), and refuses a page whose statement heading
   differs (Apple's cash flow follows its equity statement with identical geometry).
6. **Two sets of statements in one report** (Wipro prints Ind AS and IFRS). Candidates are
   grouped by page neighbourhood and one coherent group wins, with a bonus per statement it
   supplies, instead of the best page of each kind.
7. **Closing parenthesis set in its own column** (Berkshire `(21,998` `)`): joined.
8. **Expenses printed negative** (IFRS). The gross-profit reconciliation uses `|cogs|`, the same
   treatment capex already had. Spec 7.4 wrote `revenue - cogs`; this is a flagged deviation.
9. **Section-header rows** ("Net sales:") were mapping candidates and collided with their totals.
   A row is a section header only when every period cell is blank; unparseable cells still map.
10. Aliases added from the reports' own wording: "cash generated by operating activities",
    "net cash flows from operating activities", "payments for acquisition of property, plant
    and equipment", "depreciation and amortization", "net earnings (loss)".

## What is still unavailable, and why that is correct

- **Berkshire total assets**: printed with no label at all (`$ 1,069,978 $ 948,465` on a line of
  its own). Guessing the label is exactly what the design forbids. Unmapped.
- **Berkshire cash**: two rows claim it (Insurance and Other; Railroad, Utilities and Energy).
  Reported as CONFLICT with both refs.
- **Berkshire capex**: "Purchases of property, plant and equipment and equipment held for lease"
  is not an alias, and fuzzy matching is out of scope. Unmapped; the LLM fallback can pick it.
- **Apple debt**: two "Term debt" rows (current and non-current). Not aliased. Unmapped.
- **Wipro COGS and total liabilities**: Ind AS statements have neither line. Unavailable.

## Numbers seen (latest year, base units)

Apple 2023: revenue 383,285,000,000; net income 96,995,000,000; free cash flow 99,584,000,000
(derived, reconciles exactly). Wipro FY24: revenue 897,603,000,000 INR; total assets
1,147,906,000,000; assets = liabilities + equity to the rupee. Berkshire 2023: revenue
364,482,000,000; net income 97,147,000,000; earnings-quality flag fired (OCF/NI 0.51).
