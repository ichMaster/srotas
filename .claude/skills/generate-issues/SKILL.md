---
name: generate-issues
description: Decompose a ROADMAP phase into a per-phase GitHub-issues file at spec/roadmap/implementation/, ready for /upload-issues.
---

# Skill: Generate Version Issues

Decompose one ROADMAP **phase** (`vA.B`, e.g. `v0.3`) into a fine-grained,
dependency-ordered **issues file**, written to `spec/roadmap/implementation/`.
The output is the input to `/upload-issues` (which pushes it to GitHub) and then
`/execute-issues` (which implements it).

## Usage

```
/generate-issues <phase>
```

- `/generate-issues 0.2` — decompose ROADMAP phase **v0.2** → `spec/roadmap/implementation/v0.2-issues.md`
- `/generate-issues v0.5` — phase **v0.5** → `…/v0.5-issues.md`

One file per **phase** (`vA.B`). IDs (`SROTAS-xxx`) are **globally sequential**
and continue across phase files.

## Instructions

### Step 0: Read inputs

1. Normalize the phase to `vA.B` (e.g. `0.2` → `v0.2`).
2. Read [spec/ROADMAP.md](../../../spec/ROADMAP.md) §`A.B` — the phase's
   **Goal**, **Tasks**, **Out of scope**, and **DoD**.
3. Read [spec/ARCHITECTURE.md](../../../spec/ARCHITECTURE.md) for the contracts
   and components the phase touches, and
   [spec/MISSION.md](../../../spec/MISSION.md) for the principles
   (self-contained, no-LLM-in-scoring, cosine-only gate, snapshot-only Lumi
   data, auditable changes) and the binding §Scope boundaries.
4. Read `CLAUDE.md` for code conventions and the current module map.
5. **Find the next free `SROTAS-xxx` id:** scan existing
   `spec/roadmap/implementation/v*-issues.md`; continue from the highest id
   used. If none exist yet, start at `SROTAS-001`.
6. If `…/v{A.B}-issues.md` already exists, ask whether to overwrite or append.

### Step 1: Decompose the phase

Turn the phase's **Tasks** into a small set of issues (typically **3–7**), each
a coherent, independently shippable slice:

- Size each **S** (1–2 d) / **M** (3–5 d) / **L** (5–8 d).
- Order by dependency; the first issue is usually the **gate** (the seam/
  structure everything else builds on).
- Map each issue to part of the phase Tasks; together they must satisfy the
  phase **DoD**.
- **Bake tests into every issue** (Srotas mocks all paid APIs — Voyage,
  Anthropic — and all collector network calls): unit for pure logic, contract
  for any seam, an integration pass where relevant.
- A contract change (the node format, the events schema, the Item shape, the
  cosine-only gate, the embedder/classifier seams, snapshot-only access)
  carries a `spec/ARCHITECTURE.md` update + its contract test in the **same**
  issue.
- Stay **within the phase** — don't pull later phases' scope in early
  (MISSION §Scope boundaries is binding; the phase's **Out of scope** line is
  part of the spec).

### Step 2: Write the issues file

Write `spec/roadmap/implementation/v{A.B}-issues.md` using **exactly** this format:

````markdown
# v{A.B} — GitHub Issues

Issues for phase **v{A.B} — {phase title}** (version **v0 — Prototype**),
derived from the per-phase Tasks in [ROADMAP.md](../../ROADMAP.md) (§{A.B}) and
the contracts in [ARCHITECTURE.md](../../ARCHITECTURE.md) ({the relevant §
sections}). This file is scoped to a single phase; IDs continue from the
previous phase (SROTAS-{prev} → **SROTAS-{first}…{last}**).

{1–3 sentences: what the phase does, the seams it extends, why now.}

## Issues Summary Table

| # | ID | Title | Size | Area | Phase | Dependencies |
|---|----|-------|------|------|-------|--------------|
| 1 | SROTAS-{first} | {title} | M | core | v{A.B} | -- |
| 2 | SROTAS-{…} | {title} | S | web | v{A.B} | SROTAS-{first} |
| … | … | … | … | … | … | … |

**Size legend:** S = 1–2 days, M = 3–5 days, L = 5–8 days
**Areas:** memory · core · collectors · web · bootstrap · config · tests

---

## Dependency Tree

```
SROTAS-{first} ({gate})
  |
  +-- SROTAS-{…} (…) --+
  |                    |
  +-- SROTAS-{…} (…) --+
                       |
            SROTAS-{…} (…)  => {phase DoD}
```

**Parallelization hints:** {which gate first; what runs in parallel after}.

---

## v{A.B} — {phase title}

### SROTAS-{id} — {Title}

**Description:**
{1–3 sentences. Note which module(s) it touches: core/model.py, collectors/…, web/….}

**What needs to be done:**
- {bullet}
- {bullet}

**Dependencies:** {SROTAS-ids, or None}

**Expected result:**
{one sentence}

**Acceptance criteria:**
- [ ] {functional criterion}
- [ ] **Contract test:** {seam pinned} — *(only if a contract changes)*
- [ ] **Unit test:** {pure logic} against **mocks** (no paid/network call)
- [ ] {ties to the phase DoD}

---

{repeat the `### SROTAS-{id} …` block per issue}

## v{A.B} scope notes

**Total effort:** {rough estimate}.
**Critical path:** SROTAS-{…} → … → SROTAS-{…}.
**Phase DoD (ROADMAP §{A.B}):** {restate the DoD}.
**Contracts pinned this phase:** {the seams + their tests}.
**Mock note:** all paid APIs (Voyage embeddings, Anthropic classification) and
all collector HTTP (Guardian / Wikipedia / GNews) are **mocked** in tests —
never a paid or networked call in CI.
**Companion documents:**
- [ROADMAP.md](../../ROADMAP.md) — phase Goal/Tasks/Out-of-scope/DoD (§{A.B}).
- [ARCHITECTURE.md](../../ARCHITECTURE.md) — {the relevant § sections}.
- Generated on upload: `v{A.B}-github-report.md` (SROTAS-xxx → GitHub #), then `v{A.B}-execution-report.md`.
````

### Step 3: Report

Show the user: the file path, the issue count, the `SROTAS-xxx` id range, and
the critical path. Suggest the next step:

```
/upload-issues @spec/roadmap/implementation/v{A.B}-issues.md
```

(Do **not** create GitHub issues here — that's `/upload-issues`. This skill
only writes the local issues file.)

## Important Rules

- **One file per phase** (`vA.B`) at `spec/roadmap/implementation/v{A.B}-issues.md`.
- **IDs are globally sequential** (`SROTAS-xxx`), continuing across phase files — never reset per phase.
- **Tests in every issue.** Acceptance criteria include the unit/contract/integration tests; paid APIs and collector HTTP are mocked, never called live.
- **Contract = ARCHITECTURE + test together.** Any contract change lands its `spec/ARCHITECTURE.md` update and contract test in the same issue.
- **Scope to the phase.** Map issues to the phase's Tasks/DoD; honor the phase's Out-of-scope line and MISSION §Scope boundaries — don't pull later stages in early.
- **Honor the DoD.** The issues together must satisfy the phase DoD in ROADMAP §A.B.
- **Ask on ambiguity.** If the phase's Tasks are unclear or under-specified, ask the user before inventing scope.
- **Don't touch GitHub.** This skill writes only the local file; `/upload-issues` pushes it.
