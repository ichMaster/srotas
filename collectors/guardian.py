"""SROTAS-007 — the Guardian collector.

Turns each node's ``keywords`` into **one OR-joined Guardian search request per
node** (not one per keyword) and normalizes the results into :class:`~core.items.Item`
rows. Per-node OR keeps the free developer tier in budget: at 14 nodes × ~7
keywords × 6 cycles/day, per-keyword would blow past the 500/day limit; per-node
OR is ~84 calls/day (ARCHITECTURE §Collectors).

The Guardian search API returns ``webTitle``, ``webUrl``, ``webPublicationDate``
at the top level and ``trailText`` under ``fields`` (requested via
``show-fields``). Embeddings are Out-of-scope this phase — items land with
``embedding``/``score``/``top_node`` NULL for phase 0.3 to fill. All Guardian
HTTP is **mocked** in tests; never a live/paid call in CI.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import httpx

from core import config, items, model
from core.model import Node

GUARDIAN_SEARCH_URL = "https://content.guardianapis.com/search"
# Guardian caps page-size at 200; 50 keeps one modest request per node.
PAGE_SIZE = 50
_TIMEOUT = httpx.Timeout(30.0)


@dataclass(frozen=True)
class CollectSummary:
    """Counts from one collect run — ``fetched`` includes cross-node repeats."""

    nodes: int
    fetched: int
    new: int
    deduped: int


def build_query(node: Node) -> str:
    """OR-join a node's keywords into one Guardian ``q`` string.

    Each keyword is quoted so multi-word phrases match as phrases. This is the
    one-request-per-node contract: the whole node becomes a single query.
    """
    return " OR ".join(f'"{kw}"' for kw in node.keywords)


def normalize(result: dict) -> items.Item:
    """Map one Guardian search result to an :class:`~core.items.Item`."""
    fields = result.get("fields") or {}
    return items.Item(
        url=result["webUrl"],
        source="guardian",
        title=result.get("webTitle", ""),
        summary=fields.get("trailText"),
        published_at=result.get("webPublicationDate"),
    )


def _search(client: httpx.Client, query: str, api_key: str) -> list[dict]:
    """Issue one Guardian search request and return its ``results`` list."""
    resp = client.get(
        GUARDIAN_SEARCH_URL,
        params={
            "q": query,
            "api-key": api_key,
            "show-fields": "trailText",
            "order-by": "newest",
            "page-size": PAGE_SIZE,
        },
    )
    resp.raise_for_status()
    return resp.json().get("response", {}).get("results", [])


def collect_node(
    node: Node, api_key: str, *, client: httpx.Client
) -> list[items.Item]:
    """Fetch and normalize one node's articles with a single Guardian request."""
    return [normalize(r) for r in _search(client, build_query(node), api_key)]


def collect(
    nodes: Iterable[Node],
    api_key: str,
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    *,
    client: httpx.Client | None = None,
) -> CollectSummary:
    """Collect Guardian items for every node into ``items.sqlite``.

    Exactly one request per node; every result is upserted (URL dedup carries
    through — the same article surfaced by two nodes yields a single row). When
    no ``client`` is injected, one is created and closed here; tests inject a
    mock-transport client so nothing hits the network.
    """
    nodes = list(nodes)
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=_TIMEOUT)
    fetched = new = deduped = 0
    try:
        for node in nodes:
            for item in collect_node(node, api_key, client=client):
                fetched += 1
                if items.upsert(db_path, item):
                    new += 1
                else:
                    deduped += 1
    finally:
        if owns_client:
            client.close()
    return CollectSummary(nodes=len(nodes), fetched=fetched, new=new, deduped=deduped)


def run_collect(
    *,
    config_path: str | Path = config.DEFAULT_CONFIG_PATH,
    model_path: str | Path = model.DEFAULT_MODEL_PATH,
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    client: httpx.Client | None = None,
) -> CollectSummary:
    """Manual entry point: load the key + the model, then collect (SROTAS-008).

    No scheduler and no embedding pass (both Out-of-scope this phase — 0.4/0.3).
    Everything is injectable so the integration test drives the full wiring with
    a mock-transport client and temp files, never the network.
    """
    cfg = config.load_config(config_path)
    nodes = model.load_model(model_path)
    return collect(nodes, cfg.guardian_api_key, db_path, client=client)


def main() -> None:
    summary = run_collect()
    print(
        f"Guardian collect over {summary.nodes} nodes: "
        f"{summary.fetched} fetched, {summary.new} new, {summary.deduped} deduped"
    )


if __name__ == "__main__":
    main()
