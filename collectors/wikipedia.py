"""SROTAS-019 — the Wikipedia collector.

Two request shapes, both normalized into :class:`~core.items.Item` with
``source="wikipedia"`` and **``published_at=None``** — Wikipedia has no
publication date; the feed day falls back to ``first_seen``
(ARCHITECTURE §Collectors, §Item store):

- :func:`search` — one MediaWiki REST v1 search request **per node**, keywords
  OR-joined the same way as Guardian (ARCHITECTURE §Collectors).
- :func:`featured` — one request **per collection run** to the daily featured
  feed, independent of any node's keywords.

All Wikipedia HTTP is **mocked** in tests; never a live/paid call in CI.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from collectors.base import CollectSummary
from core import items
from core.model import Node

SEARCH_URL = "https://en.wikipedia.org/w/rest.php/v1/search/page"
FEATURED_URL = "https://en.wikipedia.org/api/rest_v1/feed/featured"
# The REST API has no strict daily cap like Guardian's free tier; a modest
# per-node limit keeps each request small.
SEARCH_LIMIT = 20
_TIMEOUT = httpx.Timeout(30.0)
# Wikimedia's User-Agent policy (meta.wikimedia.org/wiki/User-Agent_policy)
# rejects generic HTTP-library user agents with a 403 — a descriptive one is
# required, not optional.
_USER_AGENT = (
    "Srotas/0.6 (personal news feed prototype; "
    "https://github.com/ichMaster/srotas)"
)

__all__ = [
    "CollectSummary",
    "build_query",
    "collect",
    "featured",
    "normalize",
    "search",
]


def build_query(node: Node) -> str:
    """OR-join a node's keywords into one Wikipedia search string."""
    return " OR ".join(f'"{kw}"' for kw in node.keywords)


def normalize(page: dict) -> items.Item:
    """Map one MediaWiki search result or the featured-feed's ``tfa`` to an
    :class:`~core.items.Item`. The two REST shapes genuinely differ (confirmed
    live): a search result carries ``key`` + ``excerpt``; ``tfa`` has no
    ``key`` at all — it carries ``content_urls.desktop.page`` (the URL,
    ready-made) and ``extract`` instead."""
    content_urls = page.get("content_urls") or {}
    url = content_urls.get("desktop", {}).get("page")
    if not url:
        key = page.get("key") or page.get("titles", {}).get("canonical", "")
        url = f"https://en.wikipedia.org/wiki/{key}"
    return items.Item(
        url=url,
        source="wikipedia",
        title=page.get("title", ""),
        summary=page.get("excerpt") or page.get("extract"),
        published_at=None,
    )


def search(node: Node, *, client: httpx.Client) -> list[items.Item]:
    """One REST v1 search request for a node's OR-joined keywords."""
    resp = client.get(
        SEARCH_URL, params={"q": build_query(node), "limit": SEARCH_LIMIT}
    )
    resp.raise_for_status()
    return [normalize(page) for page in resp.json().get("pages", [])]


def featured(*, client: httpx.Client, today: date | None = None) -> list[items.Item]:
    """One request for the day's featured article — independent of any node."""
    when = today or datetime.now(UTC).date()
    resp = client.get(f"{FEATURED_URL}/{when:%Y/%m/%d}")
    resp.raise_for_status()
    tfa = resp.json().get("tfa")
    return [normalize(tfa)] if tfa else []


def collect(
    nodes: Iterable[Node],
    db_path: str | Path = items.DEFAULT_ITEMS_DB,
    *,
    client: httpx.Client | None = None,
    today: date | None = None,
) -> CollectSummary:
    """Collect Wikipedia items: one search per node, plus the day's featured
    article. URL dedup carries through (a repeat URL — e.g. the featured
    article also matching a node's search — upserts in place)."""
    nodes = list(nodes)
    owns_client = client is None
    if owns_client:
        client = httpx.Client(timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT})
    fetched = new = deduped = 0
    try:
        collected: list[items.Item] = []
        for node in nodes:
            collected.extend(search(node, client=client))
        collected.extend(featured(client=client, today=today))
        for item in collected:
            fetched += 1
            if items.upsert(db_path, item):
                new += 1
            else:
                deduped += 1
    finally:
        if owns_client:
            client.close()
    return CollectSummary(nodes=len(nodes), fetched=fetched, new=new, deduped=deduped)
