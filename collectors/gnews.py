"""SROTAS-020 — the Google News RSS collector.

Turns each node's ``keywords`` into **one OR-joined Google News RSS request per
node** (not one per keyword — same free-tier-style budget as Guardian:
per-keyword would mean ~590 unauthenticated requests/day and invite Google
rate-limiting; per-node OR is ~84 calls/day) and normalizes the entries into
:class:`~core.items.Item` rows, ``source="gnews"``. English locale only
(``hl=en-US&gl=US&ceid=US:en`` — ARCHITECTURE §Collectors).

The RSS body is fetched over an injectable ``httpx.Client`` and handed to
``feedparser`` as **bytes** — never ``feedparser.parse(url)``, which would
fetch over the network itself and bypass the mockable HTTP seam. All GNews
HTTP is **mocked** in tests; never a live/paid call in CI.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import feedparser
import httpx

from collectors.base import CollectSummary
from core import items
from core.model import Node

RSS_URL = "https://news.google.com/rss/search"
LOCALE_PARAMS = {"hl": "en-US", "gl": "US", "ceid": "US:en"}
_TIMEOUT = httpx.Timeout(30.0)

__all__ = ["CollectSummary", "build_query", "collect", "normalize", "search"]


def build_query(node: Node) -> str:
    """OR-join a node's keywords into one Google News RSS ``q`` string."""
    return " OR ".join(f'"{kw}"' for kw in node.keywords)


def _published_at(entry) -> str | None:
    parsed = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC).isoformat()


def normalize(entry) -> items.Item:
    """Map one feedparser entry to an :class:`~core.items.Item`."""
    return items.Item(
        url=entry.get("link", ""),
        source="gnews",
        title=entry.get("title", ""),
        summary=entry.get("summary"),
        published_at=_published_at(entry),
    )


def search(node: Node, *, client: httpx.Client) -> list[items.Item]:
    """One RSS request for a node's OR-joined keywords; parsed via feedparser."""
    resp = client.get(RSS_URL, params={"q": build_query(node), **LOCALE_PARAMS})
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)  # bytes → never a network fetch here
    return [normalize(entry) for entry in feed.entries]


def collect(
    nodes: Iterable[Node],
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    *,
    client: httpx.Client | None = None,
) -> CollectSummary:
    """Collect GNews items for every node into ``items.sqlite``.

    Exactly one request per node; URL dedup carries through (a repeat URL
    across nodes or sources upserts in place, not a second row).
    """
    nodes = list(nodes)
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=_TIMEOUT)
    fetched = new = deduped = 0
    try:
        for node in nodes:
            for item in search(node, client=client):
                fetched += 1
                if items.upsert(db_path, item):
                    new += 1
                else:
                    deduped += 1
    finally:
        if owns_client:
            client.close()
    return CollectSummary(nodes=len(nodes), fetched=fetched, new=new, deduped=deduped)
