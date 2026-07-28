"""SROTAS-010 — the scoring stage (``core/scoring.py``).

Single stage, **no LLM** (ARCHITECTURE §Scoring). For each scoring pass:

1. **Node centroid** = the mean of a node's keyword vectors (Voyage ``query``),
   recomputed on the fly — there is **no centroid cache** (a hand-edit of
   ``model.yaml`` must take effect on the next pass; MISSION §Scope, decision 1).
2. **Item vector** = the cached embedding of ``title + ". " + summary``.
3. **Relevance gate** on the **pure cosine**: an item is eligible for a node iff
   ``cosine(item, centroid) ≥ threshold``. The threshold **never** touches the
   weighted score — weight ranks, it does not decide existence, or a low-weight
   node could never surface an item and never recover (ARCHITECTURE §Contracts;
   MISSION decision 21).
4. **Rank**: ``score = max over eligible nodes (cosine × weight)``; the argmax
   node is stored as ``top_node`` — the "why suggested."

Only items that already carry a cached embedding are scored; embedding the NULL
rows is the backfill pass (SROTAS-011). All Voyage HTTP is **mocked** in tests.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path

from core import embeddings, items
from core.model import Node


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity; ``0.0`` if either vector has zero magnitude."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def centroid(vectors: Sequence[Sequence[float]]) -> list[float]:
    """The mean vector of ``vectors`` (all assumed the same dimension)."""
    n = len(vectors)
    if n == 0:
        raise ValueError("cannot take the centroid of zero vectors")
    dim = len(vectors[0])
    sums = [0.0] * dim
    for vec in vectors:
        for i, x in enumerate(vec):
            sums[i] += x
    return [s / n for s in sums]


def node_centroids(
    nodes: Sequence[Node],
    api_key: str = "",
    *,
    client=None,
    embed_fn: embeddings.Embedder | None = None,
) -> dict[str, list[float]]:
    """Embed each node's keywords (``query``) and return ``{node_id: centroid}``."""
    embed_fn = embed_fn or embeddings.embed
    centroids: dict[str, list[float]] = {}
    for node in nodes:
        vectors = embed_fn(node.keywords, "query", api_key, client=client)
        centroids[node.id] = centroid(vectors)
    return centroids


def score_items(
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    nodes: Sequence[Node] = (),
    *,
    threshold: float = 0.35,
    api_key: str = "",
    client=None,
    embed_fn: embeddings.Embedder | None = None,
) -> int:
    """Score every embedded item against ``nodes``; write ``score``/``top_node``.

    The gate is on the **pure cosine** (``cosine ≥ threshold``); among eligible
    nodes the winner is ``argmax(cosine × weight)``. An item that clears the gate
    for no node has its ``score``/``top_node`` cleared to NULL. Returns the number
    of items that got a ``top_node``.
    """
    centroids = node_centroids(nodes, api_key, client=client, embed_fn=embed_fn)
    weights = {node.id: node.weight for node in nodes}
    scored = 0
    for item, blob in items.read_embedded(db_path):
        vec = embeddings.from_blob(blob)
        best_score: float | None = None
        best_node: str | None = None
        for node in nodes:
            cos = cosine(vec, centroids[node.id])
            if cos < threshold:  # cosine-only gate — weight is NOT involved here
                continue
            weighted = cos * weights[node.id]
            if best_score is None or weighted > best_score:
                best_score, best_node = weighted, node.id
        items.set_score(db_path, item.url, best_score, best_node)
        if best_node is not None:
            scored += 1
    return scored
