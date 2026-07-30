"""SROTAS-011/021 — the collect → embed → score pass.

Bridges phase 0.2's NULL embeddings into the scored world and establishes the
ordered pass that every collection cycle runs (ARCHITECTURE §Scoring). Two
callables:

- :func:`embed_and_score` — the backfill: embed every item whose ``embedding`` is
  still NULL (only those — the cache is reused, never recomputed), then run the
  scoring pass. Idempotent: a second call embeds nothing and re-scores from the
  cached vectors for free.
- :func:`run_pass` — the whole sequence **collect (Guardian + Wikipedia +
  GNews) → embed new → score**, wiring all three collectors, the embedder, and
  the scorer over ``config``/``model``. All three write into the same
  ``items.sqlite``; URL-PK upsert gives cross-source dedup for free — the same
  article surfaced by two sources yields one row (ARCHITECTURE §Collectors).

There is **no scheduler** here — driving this every 4 hours is phase 0.4. All
paid/network seams (collector HTTP, Voyage embeddings) are **mocked** in tests.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from collectors import gnews, guardian, wikipedia
from collectors.base import CollectSummary
from core import config, embeddings, items, model, scoring


@dataclass(frozen=True)
class PassSummary:
    """Counts from one collect → embed → score pass."""

    collected: dict[str, CollectSummary]
    embedded: int
    scored: int


def embed_and_score(
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    nodes=(),
    *,
    threshold: float = 0.35,
    api_key: str = "",
    client=None,
    embed_fn: embeddings.Embedder | None = None,
) -> tuple[int, int]:
    """Embed the NULL-embedding items, then score every item; return
    ``(embedded, scored)``. Re-running embeds nothing (cache) and re-scores."""
    embedded = embeddings.ensure_item_embeddings(
        db_path, api_key, client=client, embed_fn=embed_fn
    )
    scored = scoring.score_items(
        db_path,
        nodes,
        threshold=threshold,
        api_key=api_key,
        client=client,
        embed_fn=embed_fn,
    )
    return embedded, scored


def run_pass(
    *,
    config_path: str | Path = config.DEFAULT_CONFIG_PATH,
    model_path: str | Path = model.DEFAULT_MODEL_PATH,
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    guardian_client=None,
    wikipedia_client=None,
    gnews_client=None,
    embed_fn: embeddings.Embedder | None = None,
) -> PassSummary:
    """The single callable pass: collect (Guardian + Wikipedia + GNews) →
    embed new → score.

    Loads the key + threshold from config and the nodes from the model.
    Injectable seams (one client per collector, an embedder) let tests drive
    the whole pass without the network; a real run creates them from config.
    """
    cfg = config.load_config(config_path)
    nodes = model.load_model(model_path)
    collected = {
        "guardian": guardian.collect(
            nodes, cfg.guardian_api_key, db_path, client=guardian_client
        ),
        "wikipedia": wikipedia.collect(nodes, db_path, client=wikipedia_client),
        "gnews": gnews.collect(nodes, db_path, client=gnews_client),
    }
    embedded, scored = embed_and_score(
        db_path,
        nodes,
        threshold=cfg.cosine_threshold,
        api_key=cfg.voyage_api_key,
        embed_fn=embed_fn,
    )
    return PassSummary(collected=collected, embedded=embedded, scored=scored)
