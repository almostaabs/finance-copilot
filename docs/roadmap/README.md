# Finance Copilot: improvement roadmap

This folder is an execution plan for `almostaabs/finance-copilot`. Every phase file is written so that a
capable coding model (e.g. Claude Sonnet) can carry it out without guessing. When a phase file and your own
judgement disagree, **the phase file wins**; if the phase file looks wrong, stop and ask the human (see
`EXECUTION_RULES.md` §7). Do not quietly improvise.

Copy this whole folder into the repo as `docs/roadmap/` before starting.

---

## What we are building, in one paragraph

Today the app extracts numbers from annual-report PDFs with full provenance, and it has been checked for
*coverage* on five real reports, but never for *correctness* against independent ground truth. The goal of
this roadmap is a product whose central claim ("never wrong, sometimes silent") is **measured**: a
public accuracy scoreboard over 100+ SEC filings plus a hand-verified Indian set. Then it adds product
features that show off provenance: fetch by ticker, click a number to see the highlighted cell in the
source PDF, multi-year trends, and a tightly grounded Q&A.

## Folder layout

```
roadmap/
├── README.md                 ← you are here: order, dependencies, how to run a phase
├── EXECUTION_RULES.md        ← invariants and conventions every phase must follow
├── VERIFICATION_GATE.md      ← the "did anything break?" check, run after EVERY phase
├── SUBAGENTS.md              ← recommended builder/evaluator split, with ready-made agent definitions
├── tier-1-credibility/       ← prove the numbers are right. Do this first. Non-negotiable.
│   ├── README.md
│   ├── T1.0-baseline-and-snapshot.md
│   ├── T1.1-xbrl-eval-harness.md
│   ├── T1.2-indian-labeled-set.md
│   ├── T1.3-eval-driven-coverage.md
│   └── T1.4-correctness-fixes.md
├── tier-2-product/           ← features that make the provenance visible and useful
│   ├── README.md
│   ├── T2.1-performance.md
│   ├── T2.2-ticker-input-and-xbrl-crosscheck.md
│   ├── T2.3-source-viewer.md
│   ├── T2.4-multi-report-trends.md
│   └── T2.5-grounded-qa.md
└── tier-3-later/             ← only after tiers 1 and 2 are green
    ├── README.md
    ├── T3.1-sector-aware-concepts.md
    ├── T3.2-peer-comparison.md
    └── T3.3-nextjs-frontend.md
```

## Execution order and dependencies

```
T1.0 ──► T1.1 ──► T1.4 ──► T1.2 ──► T1.3 ──► [TIER 1 EXIT GATE]
                                                   │
         ┌─────────────────────────────────────────┘
         ▼
T2.1 ──► T2.2 ──► T2.3 ──► T2.4 ──► T2.5 ──► [TIER 2 EXIT GATE]
                                                   │
                                                   ▼
                              T3.1 ──► T3.2 ──► (T3.3 optional)
```

Why this order:

- **T1.0 first**: it builds the regression snapshot that the verification gate depends on. Without it
  "did anything break?" cannot be answered mechanically.
- **T1.1 before T1.4**: the correctness fixes must be measured by the harness, not by eye.
- **T1.3 last in tier 1**: coverage work is only safe once there is a dev/holdout split to stop
  overfitting the alias tables.
- **T2.1 (speed) first in tier 2**: every later tier-2 feature is demoed live; a 90-second wait kills demos.
- **T2.2 before T2.3**: T2.2 creates the `sources/` module and EDGAR plumbing that T2.3's demo flow uses.

Rough effort (a guess, not a measurement; part-time): tier 1 ≈ 2 weeks, tier 2 ≈ 2 weeks, tier 3 open-ended.

## How to run one phase (the loop)

1. `git checkout main && git pull && git checkout -b roadmap/<phase-id>` (e.g. `roadmap/t1-1-xbrl-eval`).
2. Read, in this order: `EXECUTION_RULES.md`, the tier `README.md`, the phase file, then every file the
   phase lists under **Read first**.
3. Build, following the phase's numbered steps. Commit after each step that leaves tests green.
4. Run `VERIFICATION_GATE.md` in full, plus the phase's **Phase-specific checks**.
5. Write the phase log entry into `docs/ROADMAP_LOG.md` (template in `VERIFICATION_GATE.md`).
6. Only when the gate is green: merge to `main` and tick the phase in the status table below.

**Strongly recommended:** run step 3 with a *builder* subagent and step 4 with a separate, fresh *evaluator*
subagent that has never seen the builder's reasoning. An agent grading its own work is the most common way
a broken phase gets marked "done". See `SUBAGENTS.md`.

### Prompt to paste into Claude Code to start a phase

```
Execute roadmap phase <PHASE-ID> for this repository.
Read docs/roadmap/EXECUTION_RULES.md, docs/roadmap/<tier-folder>/README.md and
docs/roadmap/<tier-folder>/<PHASE-FILE>.md, then every file under "Read first".
If you can spawn subagents, follow docs/roadmap/SUBAGENTS.md: one builder subagent implements,
then a fresh evaluator subagent runs docs/roadmap/VERIFICATION_GATE.md independently.
Do not start any other phase. Stop and ask me if any "Stop and ask" condition in the phase file triggers.
When done, report: gate result, test count before/after, snapshot diff summary, eval delta (if any),
and the ROADMAP_LOG.md entry.
```

## Status

| Phase | Title | Status | Merged commit |
|---|---|---|---|
| T1.0 | Baseline and regression snapshot | ☐ | |
| T1.1 | XBRL ground-truth eval harness | ☐ | |
| T1.4 | Correctness fixes (10-K basis, plausibility flag) | ☐ | |
| T1.2 | Hand-labelled Indian set | ☐ | |
| T1.3 | Eval-driven coverage + public scoreboard | ☐ | |
| — | **Tier 1 exit gate** | ☐ | |
| T2.1 | Performance on large reports | ☐ | |
| T2.2 | Ticker input + XBRL cross-check badges | ☐ | |
| T2.3 | Source viewer with cell highlighting | ☐ | |
| T2.4 | Multi-report trends | ☐ | |
| T2.5 | Grounded Q&A | ☐ | |
| — | **Tier 2 exit gate** | ☐ | |
| T3.1 | Sector-aware concept sets | ☐ | |
| T3.2 | Peer comparison | ☐ | |
| T3.3 | Next.js frontend (optional) | ☐ | |

## Before T1.0: optional but recommended

If you ran the adversarial audit prompt (the one that writes `docs/AUDIT_<date>.md`), fix every
**CRITICAL** finding from it on its own branch *before* T1.0, so the baseline snapshot captures corrected
behaviour rather than freezing a known bug in place.
