---
name: execute-issues
description: Execute GitHub issues for a phase sequentially - implement, validate, commit, push, and generate a report.
---

# Skill: Execute GitHub Issues

Execute GitHub issues for a phase sequentially: implement, validate, commit,
push, and generate a report.

## Usage

```
/execute-issues <label> [--phase vA.B] [--issue SROTAS-xxx] [--dry-run]
```

The `<label>` is the GitHub version label exactly as it appears (e.g., `v0::version:0`).

- `/execute-issues v0::version:0 --phase v0.2` -- execute all open issues of phase v0.2
- `/execute-issues v0::version:0 --issue SROTAS-003` -- execute a single issue
- `/execute-issues v0::version:0 --phase v0.2 --dry-run` -- show the execution plan without changes

**Srotas builds one phase per release (ROADMAP §build model): execute the
issues of ONE phase, then stop.** Without `--phase`, ask the user which phase
to run rather than executing everything under the version label.

## Instructions

### Step 0: Verify prerequisites

1. Confirm we are on the expected branch (e.g., `main` or the user's working branch)
2. Confirm working tree is clean (`git status`)
3. Confirm `gh` is authenticated
4. Parse the label/phase: label `v0::version:0` + `--phase v0.2` → phase `v0.2`
5. Fetch issues from GitHub:
   ```bash
   gh issue list --label "{label}" --state open --limit 100
   ```
   and filter to the phase (the `Phase:` field in each issue body / the issues file).
6. Read the phase issues file for detailed descriptions: `spec/roadmap/implementation/v{A.B}-issues.md`
7. If a GitHub report exists (`spec/roadmap/implementation/v{A.B}-github-report.md`), read the SROTAS-to-GitHub# mapping
8. Read [spec/ROADMAP.md](../../../spec/ROADMAP.md) for the phase Goal/Tasks/Out-of-scope/DoD,
   [spec/ARCHITECTURE.md](../../../spec/ARCHITECTURE.md) for the contracts the
   issue must honor (§Contracts that must not drift), and
   [spec/MISSION.md](../../../spec/MISSION.md) §Scope boundaries (binding) +
   §Principles. `CLAUDE.md` has the code conventions.

### Step 1: Build execution queue

From the GitHub issue list, build an ordered queue based on dependencies:
- Parse SROTAS-xxx IDs from issue titles (format: `SROTAS-xxx: {title}`)
- Determine dependency order from the issues file dependency tree
- Issues with no unmet dependencies go first
- Skip issues already closed on GitHub
- If `--issue SROTAS-xxx` is specified, execute only that issue (but verify its dependencies are closed)

Show the user the execution plan and ask for confirmation.

### Step 2: Execute each issue (loop)

For each issue in the queue:

#### 2a. Assign and announce

Print: `--- Starting SROTAS-xxx: {title} ---`

#### 2b. Read issue details

Read the full issue description from the issues file (the detailed section for
this SROTAS-xxx).

#### 2c. Implement

Execute the tasks described in the issue. Follow the conventions in `CLAUDE.md`
and the principles in `spec/MISSION.md`. Route by component:

- **Memory package** (`core/model.py`, `core/events.py`, `memory/`): the flat
  node format (`id`, `label`, `keywords`, `weight` — nothing else); ruamel.yaml
  round-trip writes that preserve the human's comments; the minimal events
  schema (`id, ts, kind, node_id, payload`), append-only.
- **Collectors** (`collectors/`): normalize everything to `Item`; URL dedup;
  **one OR-joined request per node** (Guardian + GNews budgets); `published_at`
  nullable with `first_seen` fallback.
- **Scoring** (`core/scoring.py`): the **cosine-only relevance gate** (never
  threshold the weighted score); ranking `cosine × weight`; the Voyage client
  behind a mockable seam; the embedding cache in `items.sqlite`. **No LLM calls
  in scoring.**
- **Web** (`web/`): FastAPI + HTMX; **127.0.0.1 only**; filtering lives in the
  card tags; no state on the server beyond query params.
- **Feedback** (`core/feedback.py`): the Haiku classifier behind a mockable
  seam, fed the card context (title + `top_node`); deltas +0.05/−0.07 with
  clamp on the card's `top_node`; every change → an `events` row with the
  original text + item URL; `new_topic` → `pending_topics.yaml`, never a node.
- **Bootstrap** (`bootstrap/`): snapshot-only sources (hand-copied files in
  `bootstrap/snapshots/`, gitignored); the manual-review gate before
  `model.yaml` is written.
- **Contract changes:** any change to a stable seam (ARCHITECTURE §Contracts
  that must not drift) updates `spec/ARCHITECTURE.md` **AND** its contract
  test, in the same commit.
- Follow existing style/patterns; keep each phase self-contained (don't pull
  later phases' or stages' concerns in early — MISSION §Scope boundaries is
  binding).

#### 2d. Validate

Run validation checks (Python):

1. **Tests:** `pytest` (unit + the contract tests pinning the seams).
2. **Lint:** `ruff check {changed paths}` (and `ruff format --check` if configured).
3. **Syntax/import:** `python3 -m py_compile {changed_py_files}` and an import check for changed modules.
4. **Contract consistency:** the touched seams match `spec/ARCHITECTURE.md` §Contracts and their contract tests.
5. **Acceptance criteria:** go through each criterion from the issue and verify against the phase DoD in `spec/ROADMAP.md`.

Record pass/fail for each check. **Tests are part of the work.** No paid or
networked calls in validation/CI: mock Voyage, mock the Anthropic classifier,
mock all collector HTTP — never call live.

#### 2e. Commit

```bash
git add {specific files created/modified}
git commit -m "$(cat <<'EOF'
SROTAS-xxx: {title}

{1-2 sentence summary of what was implemented}

Closes #{github-issue-number}

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

#### 2f. Push

```bash
git push
```

#### 2g. Close issue with summary

```bash
gh issue close {issue-number} --comment "$(cat <<'EOF'
## Implementation Summary

**Commit:** {commit-hash}
**Files changed:** {count}

### What was done
{bullet list of key changes}

### Validation
{pass/fail status for each check}

### Acceptance criteria
{checklist with pass/fail}
EOF
)"
```

#### 2h. Log progress

Append to the in-memory execution log: issue ID + title, commit hash, files
changed, validation results, status (success/partial/failed).

### Step 3: Handle failures

If implementation or validation fails for an issue:

1. Do NOT commit broken code
2. Revert changes: `git checkout -- .`
3. Add a comment to the GitHub issue explaining what failed
4. Log the failure
5. Ask the user: continue to next issue (if no dependency), or stop?

### Step 3b: Stop at the phase boundary; no auto-release

**When the phase's issues are all done, STOP.** Do not start the next phase —
the user reviews and launches it manually (ROADMAP §build model). **Do NOT bump
the version automatically.** Never change the version (VERSION file,
RELEASE.txt, or git tag) without explicit user confirmation; report completion
and let the user decide whether/when to release via `/release-version`.

Version notation `A.B.C`: `A` = roadmap version (v0→0), `B` = phase
(`v0.3`→B=3), `C` = post-release fix. Roadmap phase `vA.B` → semver `A.B.0`
(e.g. v0.3 → `0.3.0`). If some issues failed or were skipped, do NOT release —
note in the report that the phase is incomplete.

### Step 4: Generate execution report

After all issues are processed (or on stop), generate
`spec/roadmap/implementation/v{A.B}-execution-report.md`:

```markdown
# Phase v{A.B} -- Execution Report

**Date:** {date}
**Branch:** {branch name}
**Label:** {label}
**Target release:** {A.B.0}
**Executed by:** Claude Code

## Summary

| Status | Count |
|--------|-------|
| Completed | {n} |
| Failed | {n} |
| Skipped | {n} |
| Remaining | {n} |

## Issues

| # | SROTAS ID | Title | Phase | Status | Commit | Files | Tests |
|---|-----------|-------|-------|--------|--------|-------|-------|
| 1 | SROTAS-001 | ... | v0.1 | completed | a1b2c3d | 4 | pass |

## Detailed Results

### SROTAS-001: ...
**Status:** completed · **Commit:** a1b2c3d
**Validation:** [x] pytest · [x] ruff · [x] contracts · [x] acceptance

## Next Steps
{remaining issues + dependencies; or "phase complete — awaiting user review and /release-version A.B.0"}
```

Commit and push the report (`SROTAS`-style message, with the Co-Authored-By
trailer).

## Important Rules

- **One issue at a time.** Never work on multiple issues simultaneously.
- **One phase at a time.** Execute only the given phase's issues; stop at the phase boundary — the user launches the next phase.
- **Dependency order.** Never start an issue whose dependencies are not closed.
- **Clean commits.** Each issue = one commit. No mixing work across issues.
- **No broken code.** Only commit code that passes validation (pytest + ruff).
- **Tests ship with the feature.** Mock Voyage, the Anthropic classifier, and all collector HTTP; never call paid APIs or the network.
- **Scope discipline.** MISSION §Scope boundaries is binding: no LLM in scoring, no stubs or config flags for later stages, exactly three collectors, snapshot-only Lumi data.
- **The memory package stays human-owned.** ruamel round-trip writes only; every model change writes its `events` row.
- **Contracts stay stable.** A seam change updates `spec/ARCHITECTURE.md` and its contract test in the same commit.
- **Ask on ambiguity.** If an issue description is unclear, ask the user rather than guessing.
- **Progress updates.** Print a short status line after each issue completes.
