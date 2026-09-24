# XBRL accuracy eval

Runs the pipeline on 50 US 10-K filings and scores every mapped value against
the company's own SEC XBRL facts. XBRL is filed by the company with the 10-K,
so it is independent ground truth that nobody here computed. It is used for
scoring only; it is never shown as a value or substituted for a missing one.

## What it measures

Only the 16 concepts in `concept_tags.py` (revenue, cogs, gross_profit,
operating_income, d_and_a, net_income, total_assets, current_assets, cash,
total_liabilities, current_liabilities, short_term_borrowings,
long_term_borrowings, equity, operating_cash_flow, capex). Derived values
(ebitda, total_debt, free_cash_flow) are never scored. Each concept accepts a
fixed set of us-gaap tags naming the same line item; the matched tag is
recorded on every record.

For one (filing, concept, year) with a truth value:

| Outcome | Meaning |
|---|---|
| `correct` | The app mapped a value and it matches within half the smallest printed unit |
| `wrong` | The app mapped a value and it does not match. **This is the number that matters.** Split into `sign_mismatch`, `wrong_period` (matches another year) and `value` |
| `withheld` | The app returned `Unavailable`; the recorded reason is its root cause, or `not_mapped` when no row claimed the concept |
| `unverified` | The app mapped a value the XBRL has no fact for; in no ratio |

- precision = correct / (correct + wrong)
- coverage = (correct + wrong) / (correct + wrong + withheld)
- wrong rate = wrong / (correct + wrong + withheld)

Truth is the `units.USD` facts whose `accn` is the filing's accession: 350-380
day durations for flow concepts, instants for balance-sheet concepts. The
truth year is the year of the fact's `end` date. `fy` never sets a truth
year: comparatives carry the filing's `fy`, and `fy` does not follow the
statements either (Lowe's prints "January 30, 2026" and Salesforce calls its
year ending 2026-01-31 "fiscal 2026", yet both carry `fy` 2025). A filing whose
statements print "Fiscal YYYY" one lower than the end-date year gets
`fiscal_year_offset = -1` in `corpus.csv`, applied when the frozen truth is
read; `run.py` refuses an override whose `offset_evidence` does not cite the
page and exact header text. Today only Home Depot has one. Each run lists, as
"fy-mismatch", every filing where `fy - year(latest period end)` differs from
the offset in use (also stored under `fy_mismatch` in `latest_<split>.json`):
open those filings' statement headers only, never their results, and add an
evidenced override where the header prints "Fiscal YYYY". If one tag gives two
values for a year, that (concept, year) is excluded with a note rather than
picked. Net income accepts `NetIncomeLoss`
(attributable to the parent) and `ProfitLoss` (consolidated, including
noncontrolling interests); which one the app should report is undecided (see
`docs/KNOWN_ISSUES.md`).

Truth can include years the statements do not show side by side (for example,
equity at the start of the oldest year, from the statement of shareholders'
equity). These count as `withheld`, which lowers coverage but not precision.

## Rendered vs published PDFs

EDGAR 10-Ks are HTML. Most of the corpus is that HTML rendered to PDF with
headless Chromium: no ruled table lines, so the `textgrid` path does the work,
on a layout no company designed for print. That is a different distribution
from the PDFs users upload. AAPL, MSFT, BRK-B and MBIN are scored on their
company-published PDFs (`local_pdf` in `corpus.csv`, read from
`tests/fixtures/real/` when present) so both kinds are covered. Read every
number with this in mind.

## Corpus, split, lock

- `corpus.csv`: ticker, bucket (`general` or `financial`), sector, local_pdf,
  fiscal_year_offset (empty = 0, or -1) and offset_evidence.
  Financial companies (banks, insurers) are reported separately: they have no
  classified balance sheet, so blending them would distort coverage.
- Split: `holdout` if `int(sha256(ticker), 16) % 10 < 3`, else `dev`. Never
  hand-edited. The counts print at the start of every run.
- `corpus.lock.json`: the exact filing per ticker, written on first fetch and
  only read afterwards. Automatic selection is the newest 10-K filed on or
  before 2026-06-30; for a `local_pdf` it is the 10-K whose reportDate year
  matches the year in the file name. When a lock entry exists, its CIK is used
  and the ticker is not looked up again.
- **XOM lock override:** since 2026-07-01 the SEC ticker map points XOM at
  ExxonMobil Holdings Corp (CIK 2115436), which has no 10-K. The lock is
  hand-set to CIK 0000034088, accession 0000034088-26-000045 (human decision,
  2026-09-24; see `docs/KNOWN_ISSUES.md`).
- `truth/<TICKER>_<accession>.json`: truth frozen on first run, so a later SEC
  amendment cannot move it.

## Exposed holdout companies

The holdout is only honest if nobody has looked at its results. `exposed.json`
lists holdout tickers whose results were viewed anyway, with the reason (AAPL:
viewed during the T1.1 pilot hand check). Exposed holdout companies are still
scored, but kept out of the `all`, `general` and `financial` totals and
reported in their own `exposed` section. Add a ticker there whenever holdout
results for it are read; never remove one.

## Running it

```bash
uv sync --dev --group eval && uv run playwright install chromium
export SEC_USER_AGENT="finance-copilot <your contact email>"
uv run python -m evals.run                         # dev split, all buckets
uv run python -m evals.run --only KO JPM           # a subset
uv run python -m evals.run --compare evals/results/baseline_dev.json
```

Flags: `--split dev|holdout|all` (default dev), `--bucket general|financial|all`,
`--only TICKER ...`, `--compare PATH`, `--workers N`. Do not run
`--split holdout` outside the tier exit gate.

Each run writes `results/latest_<split>.json` (every record, totals overall,
per bucket, per concept and per filing, the git SHA and a timestamp) and prints
a Markdown summary with every `wrong` record. A company that fails to fetch,
render or analyse is recorded as `status=error` with the cause and the run
continues. `--compare` prints deltas and exits 1 if `wrong` rose or precision
fell in any scope.

Requests to the SEC carry `SEC_USER_AGENT` and are spaced at least 0.15 s
apart. Downloads, rendered PDFs and companyfacts are cached in `.cache/`
(gitignored); a cached run makes no requests.
