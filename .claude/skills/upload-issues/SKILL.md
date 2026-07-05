---
name: upload-issues
description: Upload issues from a version issues file to GitHub one by one with proper labels and dependencies.
---

# Skill: Upload Version Issues to GitHub

Upload issues from a version issues file to GitHub one by one, with proper
labels (prefixed by version) and dependencies.

## Usage

```
/upload-issues <version-issues-file>
```

Example: `/upload-issues @spec/roadmap/implementation/v0.2-issues.md`

A version issues file is the fine-grained breakdown of a ROADMAP phase: each
phase (`vA.B`) in [spec/ROADMAP.md](../../../spec/ROADMAP.md) is split into one
or more `SROTAS-xxx` issues by `/generate-issues`. If the file does not exist
yet, run `/generate-issues` first, then this skill.

## Instructions

### Step 1: Read the version issues file

Read the provided file (e.g., `spec/roadmap/implementation/v{A.B}-issues.md`).

Determine from the file:
- **Version number** (n): the major from the filename or heading (e.g.,
  `v0.2-issues.md` → n = `0`)
- **Label prefix**: `v{n}::` (e.g., `v0::`)

Parse the **Issues Summary Table** to extract for each issue:
- `ID` (e.g., SROTAS-001)
- `Title`
- `Size` (S, M, L)
- `Area` (the component: `memory`, `core`, `collectors`, `web`, `bootstrap`,
  `config`, `tests`)
- `Phase` (the ROADMAP phase it implements, e.g. `v0.2`)
- `Dependencies` (list of SROTAS-xxx IDs)

Then parse each **detailed issue section** (heading with SROTAS-xxx) to
extract: `Description`, `What needs to be done`, `Dependencies`,
`Expected result`, `Acceptance criteria` (should align with the phase DoD in
ROADMAP.md).

### Step 2: Confirm with user

Show the user a summary of what will be created: number of issues, label prefix
(e.g., `v0::`), the full list of labels, and ask for confirmation before
proceeding.

### Step 3: Create labels (if they don't exist)

All labels MUST be prefixed with `v{n}::`. Label format: `v{n}::{category}:{value}`.

Version titles: **v0 — Prototype (close the cycle)**. (Later versions come
from [spec/vision.md](../../../spec/vision.md) stages as they are specced.)

```bash
# Version label
gh label create "v0::version:0" --color "0E8A16" --description "Version v0 — Prototype (close the cycle)" 2>/dev/null || true

# Size labels
gh label create "v0::size:S" --color "28A745" --description "Small (1-2 days)" 2>/dev/null || true
gh label create "v0::size:M" --color "FFC107" --description "Medium (3-5 days)" 2>/dev/null || true
gh label create "v0::size:L" --color "DC3545" --description "Large (5-8 days)" 2>/dev/null || true

# Area labels (one per component touched in this phase)
gh label create "v0::area:memory"     --color "6F42C1" 2>/dev/null || true
gh label create "v0::area:core"       --color "1D76DB" 2>/dev/null || true
gh label create "v0::area:collectors" --color "0E8A16" 2>/dev/null || true
gh label create "v0::area:web"        --color "FBCA04" 2>/dev/null || true
gh label create "v0::area:bootstrap"  --color "D93F0B" 2>/dev/null || true
# ... config / tests as needed
```

### Step 4: Create issues ONE BY ONE

**IMPORTANT:** Issues must be created one at a time, sequentially. After
creating each issue, show the user the result (issue number, URL) and proceed
to the next immediately (do not wait for confirmation between issues).

For each issue (in order from the summary table):

1. Build the issue body in markdown:

```markdown
## Description
{description}

## What needs to be done
{full content}

## Dependencies
{dependency list, with references to already-created issue numbers}

## Expected result
{expected result}

## Acceptance criteria
{checklist}

---
**ID:** {SROTAS-xxx}
**Size:** {S/M/L}
**Version:** v{n}
**Area:** {memory/core/collectors/web/bootstrap/config/tests}
**Phase:** {vA.B from ROADMAP}
```

2. Create the issue with a single `gh issue create` command (one issue per
   command, never batch):

```bash
gh issue create \
  --title "SROTAS-xxx: {title}" \
  --label "v0::version:0,v0::size:{S/M/L},v0::area:{area}" \
  --body "$(cat <<'BODY'
{issue body}
BODY
)"
```

3. Record the mapping: SROTAS-xxx -> GitHub issue #number
4. Report to user: `Created SROTAS-xxx -> #{number}: {title}`
5. If the issue depends on already-created issues, add a comment:
   ```bash
   gh issue comment {issue-number} --body "Blocked by #{dep-issue-number} (SROTAS-xxx)"
   ```
6. Move to the next issue.

### Step 5: Generate report

After all issues are created, generate
`spec/roadmap/implementation/v{A.B}-github-report.md`:

```markdown
# Phase v{A.B} -- GitHub Issues Report

**Uploaded:** {date}
**Repository:** {github repo URL}
**Total issues:** {count}

## Issue Mapping

| SROTAS ID | GitHub # | Title | Phase | Labels | URL |
|-----------|----------|-------|-------|--------|-----|
| SROTAS-001 | #5 | ... | v0.1 | v0::version:0, v0::size:S, v0::area:core | {url} |

## Labels Created

- v{n}::version:{n}
- v{n}::size:S, v{n}::size:M, v{n}::size:L
- v{n}::area:{list}
```

### Step 6: Report to user

Show the user: total issues created, link to the GitHub issues page, path to
the generated report file.

## Error Handling

- If `gh` is not authenticated, tell the user to run `gh auth login`
- If the repo has no GitHub remote yet, tell the user to create one (`gh repo create`) before uploading
- If an issue already exists with the same title, skip it and note in the report
- If label creation fails, continue (labels may already exist)
- On any failure, report what was created so far and what remains
