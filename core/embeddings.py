"""SROTAS-009 — the embedder seam (Voyage AI) + the item embedding cache.

A direct HTTP POST via httpx to ``api.voyageai.com/v1/embeddings`` (model
**voyage-3** — the same model as Lumi's RAG, so items and Lumi memory share one
vector space). ``input_type`` is ``document`` for items and ``query`` for node
centroids; the key comes from ``config.toml``. This is the **only** network in
scoring — there is **no LLM call** anywhere in the scoring path
(ARCHITECTURE §Scoring, §Contracts that must not drift).

Item vectors are cached as BLOBs in the ``items.sqlite`` ``embedding`` column, so
re-scoring after a weight change re-embeds nothing. The store keeps the bytes;
this module owns the vector<->bytes serialization (float32 via ``array``). All
Voyage HTTP is **mocked** in tests — never a paid or live call in CI.
"""

from __future__ import annotations

from array import array
from collections.abc import Callable, Sequence
from pathlib import Path

import httpx

from core import items

VOYAGE_URL = "https://api.voyageai.com/v1/embeddings"
MODEL = "voyage-3"
INPUT_TYPES = ("document", "query")
# Voyage caps a request's batch; chunk larger item sets into separate calls.
BATCH = 128
_TIMEOUT = httpx.Timeout(30.0)

# An embedder is any callable with embed()'s shape — lets scoring/tests inject.
Embedder = Callable[..., list[list[float]]]


def embed(
    texts: Sequence[str],
    input_type: str,
    api_key: str,
    *,
    client: httpx.Client | None = None,
    model: str = MODEL,
) -> list[list[float]]:
    """Embed ``texts`` with Voyage; return one vector per text, in input order.

    ``input_type`` must be ``document`` (items) or ``query`` (centroids). No LLM
    is involved — this is the embeddings endpoint only.
    """
    if input_type not in INPUT_TYPES:
        raise ValueError(f"input_type must be one of {INPUT_TYPES}, got {input_type!r}")
    if not texts:
        return []
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=_TIMEOUT)
    try:
        resp = client.post(
            VOYAGE_URL,
            headers={"Authorization": f"Bearer {api_key}"},
            json={"input": list(texts), "model": model, "input_type": input_type},
        )
        resp.raise_for_status()
        data = sorted(resp.json()["data"], key=lambda d: d["index"])
        return [d["embedding"] for d in data]
    finally:
        if owns_client:
            client.close()


def to_blob(vector: Sequence[float]) -> bytes:
    """Serialize a vector to a compact float32 BLOB for the DB cache."""
    return array("f", vector).tobytes()


def from_blob(blob: bytes) -> list[float]:
    """Decode a cached float32 BLOB back to a vector."""
    a = array("f")
    a.frombytes(blob)
    return list(a)


def item_text(item: items.Item) -> str:
    """The canonical text embedded for an item: ``title + ". " + summary``."""
    return f"{item.title}. {item.summary or ''}"


def ensure_item_embeddings(
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    api_key: str = "",
    *,
    client: httpx.Client | None = None,
    embed_fn: Embedder | None = None,
    batch: int = BATCH,
) -> int:
    """Embed and cache every item whose ``embedding`` is still NULL; return count.

    Only uncached rows are embedded — a subsequent pass makes zero embedder calls
    (the cache is reused, not recomputed). ``embed_fn`` defaults to :func:`embed`
    and is injected by tests so nothing hits the network.
    """
    embed_fn = embed_fn or embed
    pending = items.read_unembedded(db_path)
    for start in range(0, len(pending), batch):
        chunk = pending[start : start + batch]
        texts = [item_text(it) for it in chunk]
        vectors = embed_fn(texts, "document", api_key, client=client)
        for it, vec in zip(chunk, vectors, strict=True):
            items.set_embedding(db_path, it.url, to_blob(vec))
    return len(pending)
