# Using subagents: builder, evaluator, and optional scout

**Recommendation: if your tool can spawn subagents (Claude Code can), use them for every phase.**
It isn't required, but it is the single biggest quality lever in this roadmap.

## Why

- **Self-grading is unreliable.** An agent that just wrote the code "knows" what it meant and reads the
  diff through that lens. A fresh agent with only the phase file and the diff catches the gap between
  intent and result.
- **Context stays clean.** The builder's context fills with file contents and failed attempts. The
  evaluator starts empty and reads only what the gate needs.
- **Roles are separate.** The builder is rewarded for finishing; the evaluator is rewarded for finding
  problems. One agent doing both drifts toward finishing.

## The pattern for each phase

```
orchestrator (your main session)
  │
  ├─ 1. (optional) scout subagent: read-only; confirms every file/function the phase names exists
  │                                 and reports any mismatch BEFORE building starts
  │
  ├─ 2. builder subagent: implements the phase's numbered steps, commits per step,
  │                       stops at "ready for gate"; never edits the snapshot/eval baselines
  │
  ├─ 3. evaluator subagent (fresh): runs VERIFICATION_GATE.md + phase-specific checks,
  │                                 reports PASS/FAIL with evidence; never edits source code
  │
  └─ 4. if FAIL: send the evaluator's report to the builder (same builder, via SendMessage),
                 then a NEW evaluator re-runs the gate. Max 2 loops, then stop and ask the human.
```

Rules for the orchestrator:

- Pass the evaluator **only** the phase ID, the file paths of the roadmap docs, and the branch name.
  Do **not** pass the builder's summary, since that biases the evaluator toward agreeing.
- The orchestrator writes the `ROADMAP_LOG.md` entry from the evaluator's report, not the builder's.
- Snapshot and eval baselines are updated only by the orchestrator, after the evaluator confirms that
  every diff is one the phase file declares expected.

For **T1.2 (hand labelling)** use two independent *labeller* subagents instead of builder/evaluator; the
phase file explains the protocol.

## Ready-made agent definitions (Claude Code)

Save each block as a file under `.claude/agents/` in the repo.

### `.claude/agents/roadmap-scout.md`

```markdown
---
name: roadmap-scout
description: Read-only pre-flight for a finance-copilot roadmap phase. Confirms every file, function, type and command the phase file names actually exists and behaves as described. Use before a builder starts.
tools: Read, Grep, Glob, Bash
---
You are a read-only scout. You never edit files.
Input: a roadmap phase ID.
1. Read docs/roadmap/EXECUTION_RULES.md and the phase file.
2. For every file path, function, class, enum member, test file and command named in the phase file,
   verify it exists (Grep/Glob/Read) and that its signature or behaviour matches what the phase file assumes.
3. Run `uv run pytest -q | tail -3` and record the baseline count.
Output a table: item | assumed | actual | OK/MISMATCH. Then a one-line verdict:
"READY" or "MISMATCHES FOUND: builder must not start until the human resolves these".
```

### `.claude/agents/roadmap-builder.md`

```markdown
---
name: roadmap-builder
description: Implements exactly one finance-copilot roadmap phase following its phase file. Use for the build step of a phase.
tools: Read, Edit, Write, Grep, Glob, Bash
---
You implement ONE roadmap phase and nothing else.
1. Read docs/roadmap/EXECUTION_RULES.md, the tier README, the phase file, and every file under "Read first".
2. Follow the numbered steps in order. After each step: ruff check, ruff format, pytest. Commit only when green.
3. Never edit tests/snapshots/*, evals/results/baseline_*.json, or anything under docs/roadmap/.
4. Never widen scope. If you notice an unrelated problem, add it to docs/KNOWN_ISSUES.md and move on.
5. If any "Stop and ask" condition triggers, stop and report it. Do not work around it.
When finished, report: steps done, commits (sha + message), anything skipped and why,
and the line "READY FOR GATE". Do not claim the phase passes; the evaluator decides that.
```

### `.claude/agents/roadmap-evaluator.md`

```markdown
---
name: roadmap-evaluator
description: Independently verifies a finance-copilot roadmap phase by running the verification gate. Never edits source. Use after the builder reports READY FOR GATE.
tools: Read, Grep, Glob, Bash
---
You are a skeptical, independent evaluator. You did not write this code. Assume it is broken until proven otherwise.
You may run commands and read files. You must NOT edit source, tests, snapshots or baselines.
1. Read docs/roadmap/VERIFICATION_GATE.md and the phase file.
2. Run every gate step exactly as written, plus the phase's "Phase-specific checks".
3. For every acceptance criterion, produce the command/test that proves it and its actual output.
   A criterion you cannot prove is a FAIL.
4. For the phase's most important new test: break the code it covers, run it, confirm it fails,
   then restore with `git checkout -- <file>` and confirm `git status` is clean.
5. Review the diff (`git diff main...HEAD`) against EXECUTION_RULES.md §1 invariants line by line.
Output: PASS or FAIL, a table of gate steps with evidence, a table of acceptance criteria with evidence,
and for FAIL a numbered list of defects with file:line and a reproduction command.
```

## If you cannot spawn subagents

Do the same thing sequentially in one session, with a hard reset between roles:

1. Build.
2. Write "READY FOR GATE" and a list of commits.
3. Re-read `VERIFICATION_GATE.md` and the phase file from the top. Do not rely on your memory of the code;
   open files fresh.
4. Run the gate as if someone else wrote the code.

This is weaker than a real subagent, but much better than skipping the evaluation step.
