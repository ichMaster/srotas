# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Srotas — a self-contained personal news feed with an interest model that learns from free-text feedback. The end-to-end loop: **collect → score → feed → feedback → weight shift**.

The authoritative source of truth is the spec in `spec/` (kiln format, agreed 2026-07-05, all proposals resolved). Read it before implementing anything; it supersedes this file where they disagree:
- [spec/MISSION.md](spec/MISSION.md) — what Srotas is, goal/success criteria, the **binding** scope-boundaries table, principles, non-goals, relationship to Lumi, glossary, decision log (25 items).
- [spec/ARCHITECTURE.md](spec/ARCHITECTURE.md) — components, memory package, item store, collectors, scoring, feed, feedback, bootstrap, config, repo layout, **contracts that must not drift**, testing & CI.
- [spec/ROADMAP.md](spec/ROADMAP.md) — version v0 with phases 0.1…0.7 (kiln format: Goal/Tasks/Out-of-scope/DoD, ✅🟡⬜ legend), one phase per release, plus the overall v0 DoD.
- [spec/vision.md](spec/vision.md) — the owner's 6-stage vision (this prototype = stage 1) and its mapping to the parent-concept stages.

The spec is in English; the user communicates in Ukrainian — reply in Ukrainian where they do. Node `label`s in the model are Ukrainian (display data).

## Current state

Pre-implementation: the repo contains the spec plus `spec/model-candidates.yaml` — 14 interest-topic nodes extracted (Haiku clustering) from the Lumi facts layer and reviewed by the user on 2026-07-04 (verbatim personal samples stripped for privacy). This is the finalized initial model. Per ROADMAP phase 0.1, turn these candidates into `memory/model.yaml` (dropping the `evidence`/`work` metadata fields); the full multi-source bootstrap is the last phase, 0.7.

## Scope discipline (MISSION.md §Scope boundaries — binding)

Stages 2–6 of the parent concept are deliberately excluded. **Do not create stubs, empty modules, "future-proof" abstractions, or config flags for them.** Concretely:

- No LLM calls in scoring (Voyage embedding calls are allowed — they are not LLM calls). The only LLM calls are feedback classification (ARCHITECTURE.md §Feedback) and bootstrap extraction (ARCHITECTURE.md §Bootstrap).
- No node fields beyond `id`, `label`, `keywords`, `weight` (no kind/tier/half_life/related, no graph, no decay).
- No memory API endpoints, no push/notification mechanisms, no live coupling to the Lumi project — Lumi data enters only as file snapshots.
- Exactly three collectors (Guardian, Wikipedia, Google News RSS) — no plugin framework for collectors.
- Deduplication by URL only; no simhash.
- Single local process; no deploy/monitoring machinery.
- **No local ML stack**: no sentence-transformers, no torch — embeddings come from the Voyage API.

## Architecture

- **Memory package** (`memory/`: `model.yaml` + `events.sqlite` + `pending_topics.yaml`) — a separate directory, *not* part of the Srotas code; future stages will have Lumi read it. `model.yaml` is hand-editable at any time and picked up on the next scoring pass without restart; it and `pending_topics.yaml` live in git, `events.sqlite` is runtime data (gitignored). No centroid cache — centroids are computed on the fly each scoring pass.
- **Collectors** (`collectors/`) turn each node's keywords into search queries against Guardian API, Wikipedia REST API, and Google News RSS (en-US locale only: `hl=en-US&gl=US&ceid=US:en`); Guardian and GNews use **one OR-joined request per node** (not per keyword — free-tier / rate-limit budgets). Output is normalized into `Item` rows in `items.sqlite` (URL is primary key; `published_at` nullable — Wikipedia items fall back to `first_seen`). Scheduled by APScheduler *inside* the app process, every 4 hours (config). SQLite runs in WAL mode (scheduler thread + web share the DBs in one process).
- **Scoring** (`core/`) — single stage: embed `title + ". " + summary` with **voyage-3** (same model as Lumi's RAG → shared vector space for stage-4 integration) via plain httpx POST to `api.voyageai.com/v1/embeddings` (`input_type=document` for items, `query` for centroids; `VOYAGE_API_KEY` in config); node centroid = mean of its keyword vectors, computed on the fly. **Relevance gate: `cosine ≥ 0.35` on the pure cosine** (config; calibrated via the CLI preview) — the threshold never applies to the weighted score (weight ranks, it must not decide existence, else low-weight nodes can never surface and never recover). **Ranking:** `score = max over eligible nodes (cosine × weight)`, argmax stored as `top_node`. Item embeddings are cached as BLOBs in `items.sqlite` — re-scoring after a weight change is free; changing the embedding model means resetting the cache.
- **Feed** (`web/`) — FastAPI + HTMX, one screen, **bound to 127.0.0.1 only** (unauthenticated POST that spends money and mutates the model): cards sorted by score within a day (day = `published_at`, fallback `first_seen`), fresh days on top. Filtering lives in the cards themselves: each card's node tag is clickable and filters the feed to that node ("всі" resets). No separate filter-button panel, no period toggle.
- **Feedback** — a text field per card → `POST /feedback` → one Haiku-class LLM call classifies into `like | dislike | new_topic`; the classifier receives the card's context (title + `top_node`) alongside the user's text. The weight delta applies to the **card's `top_node`**: like +0.05, dislike −0.07 (config), clamped to [0.05, 1.0]; the event payload carries the item URL. `new_topic` goes to the `pending_topics.yaml` queue — never auto-creates a node; confirmation is the user hand-moving the topic into `model.yaml` (no code path).
- **Event journal** — every feedback and weight change is written to `events.sqlite` (`id, ts, kind, node_id, payload`) with the user's original text; every model change must be traceable to a specific feedback event.

## Bootstrap (two-stage)

1. **Initial model (build step 1)** — already largely done at spec time: the ~1300 non-obsolete facts from Lumi's store were clustered by Haiku into `spec/model-candidates.yaml`; after the user's manual review they become the initial `memory/model.yaml` (10–15 nodes), with a bootstrap event in `events.sqlite` recording provenance.
2. **Full bootstrap (build step 7, last)** — `bootstrap.py` + adapters over four sources, all snapshot-based, never live: Lumi raw `role=user` messages from a manually copied `store.json` snapshot in `bootstrap/snapshots/` (gitignored — private conversations; the facts/summaries/thoughts layers and the 400 MB vectors file are not used here), Claude export (`conversations.json`), browser history (copy of Chrome `History` / Firefox `places.sqlite` — the originals are locked by a running browser), and a one-time Notion Markdown export (no Notion API). LLM extraction → merge → **manual candidate review** → final model. Work topics are cut at review; a topic blacklist in config keeps collectors away from them.

Planned layout (ARCHITECTURE.md §Repository layout): `memory/`, `bootstrap/` (+ `bootstrap/snapshots/`, gitignored), `collectors/`, `core/`, `web/`, `tests/`, `config.toml` (API keys: Guardian, Voyage, Anthropic; threshold, interval, deltas, topic blacklist; gitignored).

## Stack and running

Python 3.12. Dependencies: fastapi, uvicorn, httpx, feedparser, apscheduler, ruamel.yaml, anthropic — deliberately no sentence-transformers/torch. `config.toml` is read via stdlib `tomllib`. ruamel.yaml (not pyyaml) is required so weight updates round-trip `model.yaml` without clobbering the user's comments/formatting. The whole app runs as **one process**: uvicorn with APScheduler inside. No build/test commands exist yet — establish them as the code appears and record them here.

## Build workflow (ROADMAP.md — binding)

The build is **one phase per release**. Each of the 7 phases (memory package → Guardian → scoring → web → feedback → Wikipedia+GNews → full bootstrap) ships as semver `0.N.0` (roadmap phase `vA.B` → `A.B.0`; a post-release fix bumps the patch). Implement exactly one phase, take it to its DoD, ship it, and **stop** — the user launches the next phase manually once they have no objections. Do not merge phases or pull later phases' work forward.

Each phase ships with **pytest tests** encoding its DoD, following Lumi's convention: **all paid APIs (Voyage, Anthropic) and collector network calls (Guardian/Wikipedia/GNews) are mocked — never hit paid or network in CI**. Lint gate: ruff. Changing a contract (events schema, Item shape, node format, the cosine-only gate) changes its test. `main` stays green.

## Workflow skills

A spec → issues → execute → release pipeline lives in `.claude/skills/` (ported from kiln, retargeted to Srotas — issue prefix `SROTAS-xxx`, validation with `pytest` + `ruff`, all paid/network calls mocked):

- **`/generate-issues <phase>`** — decompose a ROADMAP phase (`vA.B`) into a dependency-ordered issues file at `spec/roadmap/implementation/v{A.B}-issues.md`. IDs are globally sequential across phases.
- **`/upload-issues <file>`** — push that file to GitHub one issue at a time with `v{n}::` labels and dependency comments; writes `v{A.B}-github-report.md`.
- **`/execute-issues <label> --phase vA.B`** — implement each issue in dependency order: code → pytest + ruff → one commit per issue → close → `v{A.B}-execution-report.md`. **Stops at the phase boundary**; never auto-releases.
- **`/release-version <A.B.0>`** — bump `VERSION`, prepend `RELEASE.txt`, commit, annotated-tag, push. One phase per release. **Never bumps without explicit user confirmation.**

The pipeline uses the `gh` CLI and needs a GitHub remote (create one with `gh repo create` if absent).
