# Roadmap — Srotas

Built in order, **one phase per release**: the implementer builds exactly one
phase, takes it to its DoD, ships it as `0.N.0` (via `/release-version`), and
**stops** — the user reviews and launches the next phase manually if there are
no objections. Phases are never merged, and no phase pulls later phases' work
forward. Legend: ✅ done · 🟡 partial · ⬜ planned.

Grouping by feel: **0.1–0.3** the quiet backend (nothing visible in a browser;
verified from the terminal), **0.4–0.5** the working product (feed + learning),
**0.6–0.7** expansion (more sources, full bootstrap), **0.8–0.9** the reading
experience (Ukrainian translation + a per-card language toggle).

Every phase ships with pytest encoding its DoD; all paid APIs (Voyage,
Anthropic) and collector network calls are **mocked** — never paid or networked
in CI ([ARCHITECTURE.md](ARCHITECTURE.md) §Testing & CI). `main` stays green.
Phase `v0.N` → semver `0.N.0`; a post-release fix bumps the patch (`0.N.1`).

## v0 — Prototype (close the cycle)

### 0.1 Memory package + initial model.yaml — ⬜
**Goal:** the interest model exists on disk with an auditable origin.
**Tasks:**
- `memory/model.yaml` from the 14 reviewed nodes in
  [model-candidates.yaml](model-candidates.yaml), dropping the
  `evidence`/`work` metadata (node format: id, label, keywords, weight).
- `core/model.py` — Node class, read/write `model.yaml` via **ruamel.yaml**
  round-trip (comments and formatting survive a code write).
- `core/events.py` — create `memory/events.sqlite` (WAL), append + read events.
- Creating the package writes a `bootstrap` event recording the model's
  provenance (Lumi facts, snapshot 2026-07-04).
- **Tests:** model round-trips (load → save → load, comments preserved); events
  append + read back; the bootstrap event is present.
**Out of scope:** scoring, embeddings, collectors, bootstrap.py.
**DoD:** `model.yaml` loads into 14 Node objects; `events.sqlite` holds the
bootstrap event; pytest green.

### 0.2 Guardian collector + items.sqlite — ⬜
**Goal:** real articles land in the item store, deduplicated.
**Tasks:**
- `core/items.py` — items table (WAL), Item class, upsert with URL dedup;
  `published_at` nullable.
- `collectors/guardian.py` — **one OR-joined request per node** (free tier:
  ~84 calls/day vs 500 limit; ARCHITECTURE §Collectors).
- `config.toml` + `core/config.py` (first key — Guardian); committed
  `config.example.toml`.
- Manual CLI run (no scheduler yet).
- **Tests:** mocked Guardian response → normalized Items; URL dedup drops
  repeats; the query is built from a node's keywords.
**Out of scope:** embeddings (the `embedding` column stays NULL); the
scheduler — collection is manual.
**DoD:** a collector run fills `items.sqlite` with deduplicated Guardian items
across the 14 nodes; pytest green.

### 0.3 Scoring + CLI preview — ⬜
**Goal:** items are ranked against the model; quality verified before any UI.
**Tasks:**
- Voyage client over httpx (`input_type=document` for items, `query` for
  centroids); embed `title + ". " + summary`; cache vectors in the DB.
- `core/scoring.py` — node centroids on the fly; **relevance gate on the pure
  cosine** (0.35 start, config); ranking `score = max over eligible nodes
  (cosine × weight)`; write `score`/`top_node`.
- Backfill the embedding NULLs left by 0.2; from here embedding is part of the
  collect → score pass.
- CLI preview printing the top-20; calibrate the threshold against it.
- **Tests:** scoring math with a mock embedder (fixed vectors); the embedding
  cache is reused, not recomputed; the gate applies to the pure cosine, never
  the weighted score (a low-weight node with a high cosine still surfaces).
**Out of scope:** web, LLM rerank.
**DoD:** the CLI prints a sensible top-20; the 0.35 cosine threshold is
calibrated against it; pytest green.

### 0.4 Web feed — ⬜
**Goal:** the feed is usable in a browser and refreshes itself.
**Tasks:**
- `web/app.py` (FastAPI, **bound to 127.0.0.1 only**) + `web/templates/`
  (HTMX).
- APScheduler inside the process: every 4h collect → embed new → score.
- The card feed: fresh days on top (day = `published_at`, falling back to
  `first_seen`), cards by descending score within a day; the clickable
  node-tag filter ("all" resets).
- The feedback field renders on the card but posts nowhere yet — the handler
  arrives in 0.5.
- **Tests:** the feed route renders cards sorted by score within day, fresh
  days first; the tag filter narrows to one node; the scheduler job is
  registered (mock collection).
**Out of scope:** feedback handling, weight changes.
**DoD:** `uvicorn web.app:app` serves the feed; the scheduler collects on
interval; tag filtering works; pytest green.

### 0.5 Feedback loop, end to end — ⬜
**Goal:** plain-language feedback shifts the model, auditably, and the feed
reacts.
**Tasks:**
- `POST /feedback`; `core/feedback.py` — Haiku classifier via the anthropic
  SDK; receives the card's context (title + `top_node`) alongside the user's
  text → `{reaction, topic_hint}`.
- Weight delta on the card's `top_node`: +0.05 / −0.07, clamp [0.05, 1.0];
  ruamel round-trip write of `model.yaml`.
- `events` rows (feedback + weight_update) carrying the original text + the
  item URL.
- Re-score (free — embeddings cached) so the feed reorders immediately.
- `new_topic` → `memory/pending_topics.yaml`; confirmation is a hand-move into
  `model.yaml` (no code path).
- **Tests:** classifier (mocked, incl. malformed output; receives title +
  top_node as context) → validated reaction; like/dislike apply the deltas to
  the card's `top_node` and clamp; each change writes an event with the
  original text and the item URL; `new_topic` goes to the queue, not the
  model; model.yaml comments survive the write.
**Out of scope:** auto-creating nodes; conversational feedback via Lili
(stage 4).
**DoD:** feedback typed → classified → the weight in `model.yaml` changes →
the event is logged → the feed reorders; pytest green.

### 0.6 Wikipedia + Google News collectors — ⬜
**Goal:** the feed draws on all three sources.
**Tasks:**
- `collectors/wikipedia.py` — REST search + the daily featured feed; items
  carry no `published_at` — the feed day falls back to `first_seen`.
- `collectors/gnews.py` — feedparser, en-US locale, **one OR-joined request
  per node** (same budget strategy as Guardian).
- Wire both into the same scheduler and `items.sqlite`, deduplicated by URL;
  the same embed + score pass picks them up.
- **Tests:** each collector (mocked responses) → normalized Items;
  cross-source URL dedup; both are wired into the collection cycle.
**Out of scope:** HN/Reddit/arXiv/Telegram/YouTube (stage 5); no plugin
framework — exactly two modules.
**DoD:** the feed shows items from all three sources; pytest green.

### 0.7 Full bootstrap — ⬜
**Goal:** the interest model is (re)built from real personal sources.
**Tasks:**
- `bootstrap/bootstrap.py` + adapters: `lumi_snapshot.py` (raw `role=user`
  messages from a hand-copied `store.json`), `claude_export.py`
  (`conversations.json`), `browser_history.py` (copies of Chrome `History` /
  Firefox `places.sqlite`), `notion.py` (Markdown export).
- Chunked LLM extraction → merge duplicates → `candidates.yaml` → **manual
  review** → enrich/replace `model.yaml`.
- **Tests:** each adapter parses its snapshot format (fixtures) → text units;
  chunked extraction (mock LLM) → candidates; duplicate merge; work topics are
  separable at review.
**Out of scope:** daily windows, segmentation, citation validation,
returned/abandoned signals (all stage 2).
**DoD:** bootstrap runs over the real sources and yields a reviewed model of
10–15 nodes (closes the last overall-DoD item); pytest green.

### 0.8 Full text + Ukrainian translation (backend) — ⬜
**Goal:** every item carries its full text and a cached Ukrainian translation.
Added 2026-07-29 (MISSION §Scope, decision 26); a **display** feature, never in
scoring. Depends on the Guardian collector (0.2) and the item store — **not** on
the web feed.
**Tasks:**
- Guardian collector also requests the full body (`show-fields=…,bodyText`) →
  the item's `body` (ARCHITECTURE §Collectors).
- Migrate `items.sqlite`: add `body`, `title_uk`, `summary_uk`, `body_uk` (all
  nullable); update the **Item shape contract test** to the new column set.
- `core/translate.py` — one **Haiku-class** call (anthropic SDK) translates
  `title` + `summary` + `body` → Ukrainian in a single request; cache in the
  `*_uk` columns; only **untranslated** items are sent (cache reuse, like the
  embedding cache). Anthropic key from config.
- Extend the pass to **collect → embed → score → translate**; backfill-translate
  the items already collected.
- **Tests:** mocked Haiku translator → the three `*_uk` fields cached; only
  untranslated rows are sent and a re-run makes **zero** translator calls; the
  Guardian collector maps `bodyText` → `body`; the migrated schema matches the
  Item contract.
**Out of scope:** the feed toggle (0.9); full text for Wikipedia/GNews (their
`body` stays NULL — those sources arrive at 0.6); on-the-fly translation
(translation is cached). No new key — the Anthropic key already in config.
**DoD:** a pass fills `body` and the `*_uk` columns for Guardian items;
re-translation is free (cache); pytest green.

### 0.9 Feed language toggle — ⬜
**Goal:** the feed reads in Ukrainian, each item switchable to the original.
Depends on the web feed (0.4) and the cached translations (0.8).
**Tasks:**
- The web feed renders each card in **Ukrainian by default** (`title_uk` /
  `summary_uk`) with a per-card **toggle to the original** — an HTMX swap on the
  card, independent of other cards (ARCHITECTURE §Feed).
- An article view shows the item's `body`, translated or original per the same
  toggle.
- Fallback: an item with no cached translation (a GNews/Wikipedia item, or one
  not yet translated) shows the original and the toggle is inactive.
- **Tests:** a card renders the `*_uk` fields by default; the toggle swaps one
  card to the original without touching the others; an untranslated item falls
  back to the original.
**Out of scope:** a global language switch (per-card only, decision 26);
translating on demand (0.8 caches at collection).
**DoD:** `uvicorn web.app:app` serves the feed in Ukrainian; each card toggles
to the original independently; pytest green.

## Overall Definition of Done (v0)

- The cycle runs locally end to end: scheduled collection, the feed opens,
  feedback changes a weight, the next collection reflects the shift.
- Every model change is traceable through `events.sqlite` to a specific
  feedback.
- `model.yaml` is hand-editable without restarting the logic.
- Bootstrap has run over real sources and the model has 10–15 confirmed nodes.
  *(Closed by 0.7; until then the cycle lives on the initial 14-node model
  from Lumi facts.)*
- The feed reads in Ukrainian, with each item switchable to the original.
  *(Closed by 0.8–0.9; the core learning cycle above stands without it.)*

## Beyond v0

Stages 2–6 are out of scope here; they live in [vision.md](vision.md) and the
binding boundary table in [MISSION.md](MISSION.md) §Scope boundaries: the
extractor + ontology (stage 2), the content-filter agent in Claude Code reading
the Lili correspondence (stage 3), Lili integration with the attention model —
she proposes content and digs into reactions (stage 4), more sources with the
emphasis on YouTube (stage 5), productionization (stage 6).
