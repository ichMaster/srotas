---
name: run-phase
description: Run the full issue pipeline for one ROADMAP phase end to end — /generate-issues then /upload-issues then /execute-issues. Stops at the phase boundary; never releases.
---

# Skill: Run Phase (generate → upload → execute)

Drive one ROADMAP **phase** (`vA.B`) through the whole issue pipeline in a single
command by chaining the three existing skills in order:

1. **`/generate-issues <phase>`** — decompose ROADMAP §`A.B` into
   `spec/roadmap/implementation/v{A.B}-issues.md`.
2. **`/upload-issues <file>`** — push that file to GitHub as `SROTAS-xxx` issues
   with `v{n}::` labels + dependency comments; writes `v{A.B}-github-report.md`.
3. **`/execute-issues <label> --phase v{A.B}`** — implement each issue in
   dependency order (code → pytest + ruff → one commit per issue → push →
   close), then write `v{A.B}-execution-report.md`.

This skill only **orchestrates** the three; it never re-implements their logic.
It **stops at the phase boundary** — like `/execute-issues`, it does **not**
release (that stays a deliberate, separate `/release-version` step, per the
ROADMAP one-phase-per-release build model).

## Usage

```
/run-phase <phase>
```

- `/run-phase 0.3` — run v0.3 (scoring) through generate → upload → execute
- `/run-phase v0.6` — run v0.6 (Wikipedia + GNews collectors)

`<phase>` is a ROADMAP phase (`A.B`, with or without the leading `v`). Exactly
one phase per run — never a range, never "all remaining phases."

## Instructions

### Step 0: Parse and preflight

1. **Normalize** the phase to `vA.B` (e.g. `0.3` → `v0.3`). Derive:
   - `n` = the major (roadmap version), e.g. `v0.3` → `0`.
   - **Label** = `v{n}::version:{n}` (e.g. `v0::version:0`) — what
     `/execute-issues` filters on.
   - **Issues file** = `spec/roadmap/implementation/v{A.B}-issues.md`.
2. **Preflight checks** (fail fast — report and stop if any fails):
   - On the expected branch (usually `main`) with a **clean working tree**
     (`git status --porcelain`); if dirty, ask before proceeding.
   - `gh` is authenticated (`gh auth status`) and the repo has a GitHub remote.
   - Read [spec/ROADMAP.md](../../../spec/ROADMAP.md) §`A.B` — confirm the phase
     exists and read its Goal/Tasks/Out-of-scope/DoD.
3. **Guard against redoing a finished phase.** Check `VERSION` / `git tag` and
   the phase's issues on GitHub (`gh issue list --label "{label}" --state all`):
   - If `A.B.0` is already tagged, or the phase's issues are all **closed**, the
     phase is done — **stop and ask** whether the user really means this phase
     (they likely meant the next one). Do not silently regenerate a completed
     phase.
   - If the phase's issues are **open** (already uploaded, not yet executed),
     note it — Stage 2 will be a no-op/skip and the run resumes at Stage 3.

### Step 1: Show the plan and get ONE confirmation

Present the whole pipeline before doing anything mutating: the phase, the label,
the issues-file path, and the three stages with their side effects (creates
GitHub issues; makes one commit per issue and **pushes to `main`**; closes
issues). Get a single confirmation for the **entire** run.

This one approval **covers each sub-skill's own confirmation prompt** — when you
run the sub-skills below, treat the pipeline as already approved and do **not**
re-ask the same question. Only pause again for a genuine fork (see Step 3).

### Step 2: Run the three stages in order

Invoke each sub-skill via the Skill tool, in sequence, passing the derived args.
**Between stages, verify the previous stage actually succeeded** (its output
artifact exists / its success criterion was met) before starting the next. If a
stage fails, **abort the chain** — do not start the next stage — and jump to
Step 4.

1. **Generate** — invoke `generate-issues` with `<phase>`.
   - If `v{A.B}-issues.md` **already exists**: this is a fork — pause and ask
     whether to **reuse it as-is** (skip regeneration, go straight to Stage 2)
     or **regenerate/overwrite** it. Don't overwrite an existing breakdown
     silently.
   - Success criterion: `spec/roadmap/implementation/v{A.B}-issues.md` exists
     and parses (has an Issues Summary Table with `SROTAS-xxx` rows).

2. **Upload** — invoke `upload-issues` with the issues file
   (`@spec/roadmap/implementation/v{A.B}-issues.md`).
   - It creates labels, then issues one-by-one, and writes
     `v{A.B}-github-report.md`. Duplicate titles are skipped by that skill — so
     a partially-uploaded phase resumes cleanly.
   - Success criterion: every `SROTAS-xxx` in the issues file maps to an open
     GitHub issue and `v{A.B}-github-report.md` exists.

3. **Execute** — invoke `execute-issues` with `{label} --phase v{A.B}`.
   - It implements each issue in dependency order (code → pytest + ruff → one
     commit per issue → push → close), writes `v{A.B}-execution-report.md`, and
     **stops at the phase boundary**.
   - Success criterion: all the phase's issues are closed and the execution
     report records pytest green + ruff clean.

### Step 3: Stop points (when to break the chain and ask)

Run straight through **except** at these genuine forks:

- The issues file already exists (Stage 1 — reuse vs regenerate).
- A preflight/guard check flags the phase as already done (Step 0.3).
- Any stage's validation fails — a failing `pytest`/`ruff`, a push rejected, an
  issue that can't be created/closed. **Never** push broken code to keep the
  chain moving; abort and report.
- A sub-skill itself asks a question you can't answer from the phase's spec
  (e.g. an ambiguous task). Surface it rather than guessing.

### Step 4: Final report

After the chain completes (or aborts), summarize the whole run:

- **Stage 1:** issues file path + issue count + `SROTAS-xxx` id range.
- **Stage 2:** GitHub issues created (SROTAS-xxx → #), report path.
- **Stage 3:** per-issue commit hashes, pytest/ruff status, execution-report
  path; or, on abort, what completed and what remains.
- **Next step:** the phase is at its DoD but **unreleased** — suggest the
  explicit, separate release:

  ```
  /release-version {A.B}.0
  ```

## Important Rules

- **Orchestrate, don't reimplement.** Call `generate-issues`, `upload-issues`,
  `execute-issues` — never inline or fork their logic. This skill's job is the
  ordering, the handoffs, and the stop points.
- **One phase per run.** Exactly the phase in the parameter; never a range and
  never "the rest of the roadmap." One phase per release is binding
  (ROADMAP build model).
- **Stop before release.** The chain ends at the phase boundary. **Never** bump
  the version, tag, or run `/release-version` — the user launches that
  deliberately after review.
- **One confirmation, then flow.** Get a single upfront approval covering all
  three stages; don't re-prompt for each sub-skill. Still pause at the genuine
  forks in Step 3.
- **Abort on failure.** A stage that fails validation stops the chain — the next
  stage never starts. Report what completed. `main` stays green; never push
  broken code to keep going.
- **Don't redo a finished phase.** If the phase is already released or fully
  closed, stop and confirm the target before regenerating anything.
- **Idempotent-friendly.** Rely on the sub-skills' own resume behavior
  (`upload-issues` skips duplicate titles; `execute-issues` skips closed issues)
  so a re-run of a partial phase picks up where it left off.
- **Ask on ambiguity.** Defer to the sub-skills' questions and the phase spec;
  if something is genuinely unclear, ask rather than invent scope.
