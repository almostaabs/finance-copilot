# Verification gate: run after EVERY phase

A phase is not done until every step below passes. "The code runs" is not the bar. The bar is "nothing
that worked before is broken, and the phase's acceptance criteria are demonstrably met".

Ideally a **fresh evaluator subagent** runs this gate, not the agent that wrote the code (see `SUBAGENTS.md`).
If you are one agent doing both, finish building, then re-read the phase file from the top as if someone
else wrote the code, then run the gate.

Record every result in the phase log entry (template at the bottom).

---

## Step 1: Clean state

```bash
git status                 # must be clean apart from intended changes; nothing untracked that should be ignored
uv sync --dev              # add --group eval from T1.1 onward
```

Fail if: untracked PDFs, cache directories, `.env`, or keys appear in `git status`.

## Step 2: Lint and format

```bash
uv run ruff check .
uv run ruff format --check .
```

Pass: both exit 0.

## Step 3: Test suite

```bash
uv run pytest -q 2>&1 | tail -5
```

Pass: 0 failures, 0 errors. Record the passed count. It must be **≥ the count recorded by the previous
phase** in `docs/ROADMAP_LOG.md`, unless this phase's log explains each removed test.

## Step 4: Regression snapshot (exists from T1.0 onward)

```bash
uv run python scripts/snapshot.py --check
```

This re-runs the pipeline with AI off over every synthetic fixture (and every real report present locally in
`tests/fixtures/real/`), and diffs the canonical output against the committed snapshot.

- **No diff** → pass.
- **Diff** → for each changed line, the phase file must say this change is expected (e.g. T1.4 expects the
  Microsoft basis to change). If it is expected: run `--update`, commit the new snapshot **in its own
  commit** titled `snapshot: <reason>`, and paste the diff summary into the log. If it is **not** expected:
  the phase broke something. Fix it or revert. Do not update the snapshot to make the gate pass.

## Step 5: Accuracy eval (exists from T1.1 onward)

```bash
uv run python -m evals.run --split dev --compare evals/results/baseline_dev.json
```

Pass criteria:

- `wrong` count did **not increase**. This is a hard rule with no exceptions and no "net improvement" trade-offs.
- `precision` did not decrease.
- `coverage` did not decrease, unless the phase log explains why (e.g. a new plausibility check now withholds
  values that were previously shown, which is the intended trade).

If the phase intentionally improved results, save the new baseline:
`cp evals/results/latest_dev.json evals/results/baseline_dev.json` in its own commit.

Holdout (`--split holdout`) is run **only at tier exit gates**. Never look at holdout failures while building.

## Step 6: App smoke test

```bash
uv run pytest tests/test_app.py -q
timeout 40 uv run streamlit run app.py --server.headless true --server.port 8599 &
sleep 20 && curl -fsS http://localhost:8599/_stcore/health && echo OK
kill %1
```

Pass: tests pass and the health endpoint returns `ok`. If a browser tool is available, also load the page,
press **Load sample report**, and confirm the Results tab renders without an exception box.

## Step 7: Invariant spot-check

Answer each with evidence (a grep, a test name, or a traced code path). "I believe so" is not an answer.

1. Did any new code create a financial number without `FinancialValue.from_cell` / `.derived`?
   (`grep -rn "FinancialValue(" src/` should only show `types.py`.)
2. Did any new code return `None`/`0` where it should return `Unavailable`?
3. Did any new code round a number outside `display.py`? (`grep -rn "quantize\|round(" src/`, then
   check each new hit.)
4. Does any new HTML output escape PDF-derived strings?
5. Did any network or model call get added outside `src/fincopilot/sources/`, `src/fincopilot/ai/` or `evals/`?

## Step 8: Acceptance criteria

Go through the phase file's **Acceptance criteria** one by one. For each, write the command or test that
proves it and its result. A criterion without proof counts as a failure.

## Step 9: Docs sync

- README Status line test count matches Step 3.
- Every new command in the phase appears in the README or the relevant doc.
- `docs/KNOWN_ISSUES.md` updated (fixed items closed, new items added).

---

## Failure protocol

1. Identify the root cause. Do not patch the symptom (see the debugging rules in `EXECUTION_RULES.md`).
2. At most two focused fix attempts.
3. Still failing → `git reset --hard <last green commit>` on the phase branch, write a log entry with
   status **BLOCKED**, what failed, and what you tried. Then stop and ask the human.

---

## Phase log template (append to `docs/ROADMAP_LOG.md`)

```markdown
## <PHASE-ID>: <title>. <PASS | BLOCKED>, <YYYY-MM-DD>

- Branch / merge commit: `roadmap/<id>` / `<sha>`
- Tests: <before> → <after> passed (removed: <none | list + reason>)
- Lint/format: pass
- Snapshot: <no diff | N lines changed, all expected: summary>
- Eval (dev): wrong <a→b>, precision <x→y>, coverage <x→y> (or "n/a before T1.1")
- App smoke: pass
- Invariant spot-check: 1 ✔ 2 ✔ 3 ✔ 4 ✔ 5 ✔ (one line of evidence each)
- Acceptance criteria: <criterion → proof>, one line each
- New dependencies: <none | name + why>
- Most important test and proof it can fail: <test name, what was broken, observed failure>
- Known issues added/closed: <list>
- Surprises / notes for the next phase: <free text, short>
```
