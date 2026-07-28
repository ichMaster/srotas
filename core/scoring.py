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

import argparse
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from core import config, embeddings, items, model
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


# --- CLI preview (SROTAS-012) ---------------------------------------------


@dataclass(frozen=True)
class PreviewRow:
    """One row of the top-N preview; ``cosine`` is recovered as score / weight."""

    rank: int
    score: float
    cosine: float
    top_node: str
    source: str
    title: str
    url: str


def preview(
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    nodes: Sequence[Node] = (),
    *,
    threshold: float = 0.35,
    top_n: int = 20,
    api_key: str = "",
    client=None,
    embed_fn: embeddings.Embedder | None = None,
) -> list[PreviewRow]:
    """Score at ``threshold`` (calibration is free — vectors are cached), then
    return the top ``top_n`` items by descending score."""
    score_items(
        db_path,
        nodes,
        threshold=threshold,
        api_key=api_key,
        client=client,
        embed_fn=embed_fn,
    )
    weights = {node.id: node.weight for node in nodes}
    rows: list[PreviewRow] = []
    for rank, (url, source, title, score, top_node) in enumerate(
        items.read_top_scored(db_path, top_n), start=1
    ):
        weight = weights.get(top_node, 1.0)
        cos = score / weight if weight else 0.0
        rows.append(PreviewRow(rank, score, cos, top_node, source, title, url))
    return rows


def format_preview(rows: Sequence[PreviewRow]) -> str:
    """Render preview rows as an aligned table for the terminal."""
    if not rows:
        return "(no items cleared the cosine gate — lower --threshold to see more)"
    header = f"{'#':>2}  {'score':>6}  {'cos':>5}  {'top_node':<26}  title"
    lines = [header, "-" * len(header)]
    for r in rows:
        lines.append(
            f"{r.rank:>2}  {r.score:>6.3f}  {r.cosine:>5.3f}  "
            f"{r.top_node:<26.26}  {r.title[:58]}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m core.scoring")
    parser.add_argument(
        "--preview", action="store_true", help="print the top-N scored items"
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=None,
        help="override the cosine gate for calibration (default: config value)",
    )
    parser.add_argument("--top", type=int, default=20, help="how many items to show")
    args = parser.parse_args(argv)

    if not args.preview:
        parser.print_help()
        return

    cfg = config.load_config()
    nodes = model.load_model()
    threshold = args.threshold if args.threshold is not None else cfg.cosine_threshold
    rows = preview(
        items.DEFAULT_ITEMS_DB,
        nodes,
        threshold=threshold,
        top_n=args.top,
        api_key=cfg.voyage_api_key,
    )
    print(f"cosine gate ≥ {threshold:.2f} · top {len(rows)}")
    print(format_preview(rows))


if __name__ == "__main__":
    main()
