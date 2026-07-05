# Srotas — Vision

The owner's staged vision (recorded 2026-07-05), the frame the prototype fits
into. Stage numbering matches the parent concept (`srotas-concept.md` v0.3) and
the binding boundary table in [MISSION.md](MISSION.md) §Scope boundaries.
**Stage 1 is this spec** ([MISSION.md](MISSION.md) / [ARCHITECTURE.md](ARCHITECTURE.md) /
[ROADMAP.md](ROADMAP.md) v0).

## The stages

1. **Prototype.** A very simple skeleton that closes all modules in minimal
   form. Sources to start: The Guardian, Wikipedia, Google recommendations —
   a ready-made aggregator. A simplified interest model as basic topics/nodes
   with signals. Presentation as a news feed. A feedback loop through short
   text feedback. A separate web application.
   *Implementation note:* there is no public API to the personal Google feed
   (Discover), so the prototype substitutes **Google News RSS keyword search**
   (decision 4, ARCHITECTURE §Collectors) — our own queries, not Google's
   ready personalization.

2. **MVP: extractor + ontology.** Focus on the interest extractor and building
   the ontology (daily windows, InterestEvent with evidence, node kinds/tiers/
   decay, canonicalization, the "gardener").

3. **MVP: content filter + relevant search.** Focus on filtering content and
   finding what is relevant. Planned mechanism: **an agent in Claude Code that
   reads the Lili correspondence** to judge relevance (LLM rerank, annotations,
   relevance explanations, active search per node).

4. **MVP: feedback loop + attention model.** Integration with Lili: **she
   proposes content herself** and digs in detail into what was liked and what
   wasn't. The Curiosity need, the attention model, the `/interests`
   `/findings` `/feedback` APIs.

5. **MVP: diverse content, especially YouTube.** More collectors: RSS/blogs,
   HN + Reddit, arXiv, Telegram, and YouTube as the emphasis.

6. **Productionization.** Deploy, monitoring, weekly quality audit, simhash
   deduplication.

## How the stages map

| Vision stage | Parent-concept stage | Where recorded |
|---|---|---|
| 1 Prototype | Stage 1 | This spec: MISSION / ARCHITECTURE / ROADMAP v0 (phases 0.1–0.7) |
| 2 Extractor + ontology | Stage 2 | MISSION §Scope boundaries, row 1 |
| 3 Content filter + search (Claude Code agent over Lili correspondence) | Stage 3 | MISSION §Scope boundaries, row 2 |
| 4 Feedback + attention (Lili proposes content) | Stage 4 | MISSION §Scope boundaries, row 3 |
| 5 Diverse content, YouTube emphasis | Stage 5 | MISSION §Scope boundaries, row 4 |
| 6 Productionization | Stage 6 | MISSION §Scope boundaries, row 5 |

The prototype's job is to make the cycle real and lived-in; each MVP then
deepens one dimension of it without rewriting the others.
