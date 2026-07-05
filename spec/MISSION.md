# Mission — Srotas

Status: agreed, ready for implementation (2026-07-05). Companion documents:
[ARCHITECTURE.md](ARCHITECTURE.md) (components, contracts, testing) ·
[ROADMAP.md](ROADMAP.md) (phased build, one phase per release) ·
[vision.md](vision.md) (the owner's staged vision this prototype opens).

## In one sentence

Srotas is a **self-contained personal news feed** whose interest model **learns
from free-text feedback** — collect → score → feed → feedback → weight shift,
all in one local process, with every model change auditable.

## What we are building

**Goal:** close the end-to-end cycle **collect → score → feed → feedback →
weight shift** on minimal versions of every module, and start using it daily.

**Success criterion:** after one or two weeks of use, node weights are visibly
shifted by feedback, the top of the feed is subjectively more relevant than on
day one, and every shift is traceable through the event journal.

In one breath: the **interest model** (flat topic nodes with weights, a
hand-editable `model.yaml`) turns into search queries; three collectors
(Guardian, Wikipedia, Google News RSS) fill `items.sqlite` every 4 hours;
scoring embeds items with **voyage-3**, gates by **pure cosine**, and ranks by
`cosine × weight`; a FastAPI + HTMX feed shows cards; a plain-text reaction on a
card is classified by one Haiku-class call into like / dislike / new-topic and
arithmetically shifts the node's weight; every change lands in `events.sqlite`.
The full design is in [ARCHITECTURE.md](ARCHITECTURE.md).

This prototype is **stage 1** of the larger staged vision
([vision.md](vision.md)); the parent concept is `srotas-concept.md` (v0.3),
which this spec is read and implemented independently of.

## For whom

A private, single-user tool for its author — never a public service. It is also
the first stone of the srotas concept: later stages grow the extractor and
ontology, a content-filter agent, Lili integration, and more sources.

## Scope boundaries — binding for the implementing agent

Everything in the table below is deliberately excluded from the prototype and
planned for specific later stages (numbering follows the parent concept; the
owner's phrasing of the same stages is in [vision.md](vision.md)). **Do not
implement it, and do not create stubs, empty modules, "grow-into-it"
abstractions, or config flags for it.** The only sanctioned preparation for the
future is already in this spec: the memory package as a separate directory, and
the events journal.

| Planned for | What exactly | What NOT to do in the prototype |
|---|---|---|
| Stage 2 | Extractor over daily windows: segmentation, InterestEvent with quote-evidence, validation, derived returned/abandoned signals. Ontology: kind, tier, decay, typed edges, canonicalization, a "gardener" | Do not complicate the events schema; do not add kind / tier / half_life / related fields to nodes; do not build windows or segmentation in bootstrap |
| Stage 3 | Two-stage scoring: LLM rerank, annotations, relevance explanations; active content search per node. Planned mechanism: **an agent in Claude Code that reads the Lili correspondence** to judge relevance | No LLM calls in scoring. The only LLM calls allowed in the prototype are feedback classification (ARCHITECTURE §Feedback) and bootstrap extraction (ARCHITECTURE §Bootstrap) |
| Stage 4 | Lumi integration: conversational feedback through Lili — **she proposes content herself** and digs into what was liked and what wasn't; a Curiosity need, an attention model, `/interests` `/findings` `/feedback` APIs | Do not build memory API endpoints; do not import anything from kiln; no push mechanisms or notifications |
| Stage 5 | Collectors for RSS/blogs, HN + Reddit, arXiv, Telegram, **YouTube (the emphasis)** | Do not build a "universal pluggable collector framework" — exactly the three concrete modules in ARCHITECTURE §Collectors |
| Stage 6 | Productionization: deploy, monitoring, weekly quality audit, simhash deduplication | Local single-process run; deduplication by URL only |

## Principles

- **Self-contained.** Srotas runs as one local process and depends on no other
  project at runtime. Lumi data enters only as **file snapshots** copied in by
  hand — never a live connection, never an import of Lumi/kiln code.
- **Shared vector space with Lumi.** Embeddings use **voyage-3**, the same model
  as Lumi's RAG, so Srotas items and Lumi memory vectors live in one space. This
  is the one forward-looking choice: at stage 4, news can be compared to
  memories directly. It costs nothing extra today.
- **The model is a plain file the human owns.** `model.yaml` is hand-editable at
  any time and picked up on the next scoring pass without a restart. Code that
  changes weights must preserve the human's comments and formatting.
- **Every change is auditable.** Each feedback and each weight change is written
  to `events.sqlite` with the user's original text. Any model change can be
  traced back to a specific feedback event.
- **Weight ranks; cosine decides existence.** The relevance gate applies to the
  pure cosine, never to the weighted score — a low-weight node can always
  surface a strongly relevant item and be liked back up.
- **No local ML stack.** No sentence-transformers, no torch. Embeddings come
  from the Voyage API over plain HTTP. The app stays light.
- **Built one phase at a time.** Each roadmap phase ships as its own release;
  the user reviews and launches the next. See [ROADMAP.md](ROADMAP.md).

## Non-goals

- Not a universal aggregator or a collector framework — exactly three sources in
  the prototype.
- **No ML training anywhere, ever.** "Learning" is arithmetic on weights;
  embeddings and classification are calls to ready-made models.
- No public service, no multi-user, no push or notifications.
- Not a Lumi rebuild and not yet a Lumi integration — until stage 4, Lumi is a
  data source via snapshots, nothing more.

## Relationship to Lumi

Srotas neither imports Lumi nor talks to a running Lumi. It uses Lumi only as a
**data source, via snapshots**:

- The **initial interest model** was seeded from Lumi's `facts` layer — ~1300
  non-obsolete facts about the user, already distilled by Lumi, clustered by
  Haiku into 14 topic nodes (ARCHITECTURE §Bootstrap; the reviewed candidates
  live in [model-candidates.yaml](model-candidates.yaml)).
- The **full bootstrap** (the last roadmap phase) reads a hand-copied snapshot
  of `lumi/.lumi/store.json` for raw `role=user` messages, alongside a Claude
  export, browser history copies, and a Notion Markdown export.

Because both projects embed with voyage-3, a future stage-4 integration can
place a news item and a Lumi memory in the same vector space with no
re-embedding.

## Glossary

- **Node** — one interest topic in the model: `id`, `label`, `keywords`,
  `weight`. Flat, no graph, no decay.
- **Interest model** — `model.yaml`, the list of nodes. Drives collection
  queries and scoring.
- **Centroid** — a node's mean keyword vector; recomputed on the fly each
  scoring pass (no cache).
- **Item** — one collected article, keyed by URL in `items.sqlite`.
- **top_node** — the node that scored an item highest; shown on the card as
  "why suggested" and the target of that card's feedback delta.
- **Relevance gate** — the cosine threshold (0.35 start) an item must clear
  against a node's centroid to be eligible; applied to the pure cosine, never
  the weighted score.
- **Memory package** — the `memory/` directory (`model.yaml` +
  `events.sqlite` + `pending_topics.yaml`), kept separate from the code so Lumi
  can read it in later stages.
- **Bootstrap** — the one-off extraction that builds the interest model from
  personal sources.
- **Snapshot** — a hand-copied file (Lumi store, browser history) that Srotas
  reads offline; never a live connection.
- **pending_topics** — the queue (`memory/pending_topics.yaml`) where
  `new_topic` feedback lands for manual confirmation; nodes are never
  auto-created.

## Decision log

### Agreed 2026-07-04

1. Centroid cache `centroids.npz` — **dropped**: centroids computed on the fly (ARCHITECTURE §Scoring).
2. Work off a copy of browser-history files — **accepted** (ARCHITECTURE §Bootstrap).
3. Manual review of candidates before writing `model.yaml` — **accepted** (ARCHITECTURE §Bootstrap).
4. Google News RSS locale — **en-US only** (ARCHITECTURE §Collectors).
5. Collection interval — **4 hours** (ARCHITECTURE §Collectors).
6. Item embedding cache in the DB — **accepted**; mandatory given the paid API (ARCHITECTURE §Item store).
7. Cutoff threshold — **0.35 as a start**, calibrated via the CLI preview (ARCHITECTURE §Scoring).
8. Embedding model — **voyage-3, same as Lumi** (shared vector space); MiniLM / sentence-transformers / torch rejected (ARCHITECTURE §Scoring).
9. Feed filtering — **clickable node tags on cards**, no button panel or period toggle (ARCHITECTURE §Feed).
10. Weight deltas +0.05 / −0.07 clamped to [0.05, 1.0] — **accepted** (ARCHITECTURE §Feedback).
11. `pending_topics` queue instead of auto-creating nodes — **accepted** (ARCHITECTURE §Feedback).
12. Repository structure and stack — **accepted**, no sentence-transformers (ARCHITECTURE §Repository layout).
13. Build order — **accepted**, with an initial model from Lumi facts instead of a 3-node hand model (ARCHITECTURE §Bootstrap, ROADMAP).
14. Notion — **one-off Markdown export**, no API (ARCHITECTURE §Bootstrap).
15. "Lili conversations" source — **snapshot of `lumi/.lumi/store.json`** (hand copy into `bootstrap/snapshots/`), not live access; kiln no longer appears as a data source (ARCHITECTURE §Bootstrap).
16. Primary source for full extraction — **raw `role=user` messages**; the facts layer seeds the initial model (ARCHITECTURE §Bootstrap).
17. Voyage is called **via httpx**, no separate SDK (ARCHITECTURE §Scoring, §Repository layout).
18. Build model — **each phase is its own release `0.N.0`**; the implementer stops after a phase, the user launches the next manually if there are no objections (ROADMAP).
19. Tests — **as in Lumi**: pytest per phase, paid and network calls mocked, `main` green (ARCHITECTURE §Testing & CI, ROADMAP).
20. `model.yaml` is written with **ruamel.yaml** (round-trip, comments preserved); pyyaml rejected (ARCHITECTURE §Memory package, §Feedback, §Repository layout).

### Spec review addendum — 2026-07-05

21. The cutoff threshold applies to the **pure cosine** (topicality gate); `cosine × weight` is used for **ranking only**. Rationale: cosine ≤ 1, so a threshold on the weighted score makes any node with weight < threshold mathematically unable to ever surface an item — and since weights grow only through likes on visible items, it could never recover. Amends the *application* of decision 7; the 0.35 starting value stands (ARCHITECTURE §Scoring, §Contracts).
22. The feedback delta applies to the **card's `top_node`**; the classifier receives the card context (title + node) alongside the user's text; the event payload carries the item URL (ARCHITECTURE §Feedback).
23. Google News RSS — **one OR-joined request per node**, same strategy as Guardian (~84 vs ~590 unauthenticated calls/day) (ARCHITECTURE §Collectors).
24. Housekeeping: `published_at` is nullable, the feed day falls back to `first_seen` (Wikipedia has no publication dates); `events.sqlite` is gitignored while `model.yaml` + `pending_topics.yaml` are tracked; a pending topic is confirmed by hand-editing `model.yaml` (no code path); the web app binds to 127.0.0.1 only; SQLite runs in WAL mode (ARCHITECTURE §Memory package, §Item store, §Feed, §Feedback).

### Reformat addendum — 2026-07-05

25. Spec reshaped to the **kiln format**: `spec/MISSION.md` + `spec/ARCHITECTURE.md` + `spec/ROADMAP.md` + `spec/vision.md`, with the issue pipeline skills (`/generate-issues` → `/upload-issues` → `/execute-issues` → `/release-version`) ported from kiln under `.claude/skills/` (issue prefix `SROTAS-xxx`, per-phase releases `0.N.0`).
