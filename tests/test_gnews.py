"""SROTAS-020 — GNews collector: one OR-joined request per node, en-US locale,
field mapping via feedparser, and URL dedup. All HTTP is mocked via
httpx.MockTransport; never a live or paid call.
"""

import httpx

from collectors import gnews
from core import items
from core.model import Node

RSS_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
<title>Google News</title>
<item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
  <description>{summary}</description>
</item>
</channel>
</rss>
"""


def _rss(title="Headline", link="https://example.com/a", summary="A plain summary."):
    return RSS_TEMPLATE.format(title=title, link=link, summary=summary).encode()


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_build_query_or_joins_keywords():
    node = Node("n", "Н", ["large language models", "AI agents"], 0.8)
    assert gnews.build_query(node) == '"large language models" OR "AI agents"'


def test_normalize_maps_entry_fields():
    import feedparser

    feed = feedparser.parse(_rss("Test Headline", "https://example.com/x", "Sum."))
    item = gnews.normalize(feed.entries[0])
    assert item.url == "https://example.com/x"
    assert item.source == "gnews"
    assert item.title == "Test Headline"
    assert item.summary == "Sum."
    assert item.published_at == "2026-07-30T12:00:00+00:00"


def test_one_request_per_node_with_or_query_and_locale(tmp_path):
    """Exactly one request per node; en-US locale params always present."""
    nodes = [
        Node("a", "А", ["alpha one", "alpha two"], 0.8),
        Node("b", "Б", ["beta"], 0.5),
    ]
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=_rss(link=f"https://ex.com/{len(seen)}"))

    gnews.collect(nodes, tmp_path / "items.sqlite", client=_client(handler))

    assert len(seen) == 2  # one request per node, not per keyword
    assert seen[0].url.params["q"] == '"alpha one" OR "alpha two"'
    assert seen[1].url.params["q"] == '"beta"'
    for request in seen:
        assert request.url.params["hl"] == "en-US"
        assert request.url.params["gl"] == "US"
        assert request.url.params["ceid"] == "US:en"


def test_collect_writes_normalized_items(tmp_path):
    db = tmp_path / "items.sqlite"
    node = Node("a", "А", ["kw"], 0.8)

    def handler(request):
        return httpx.Response(200, content=_rss("First", "https://ex.com/a", "s1"))

    summary = gnews.collect([node], db, client=_client(handler))
    assert summary.new == 1
    (item,) = items.read_items(db)
    assert item.title == "First"
    assert item.source == "gnews"
    assert item.summary == "s1"
    assert item.published_at is not None


def test_same_url_across_two_nodes_dedups_to_one_row(tmp_path):
    db = tmp_path / "items.sqlite"
    nodes = [Node("a", "А", ["kw1"], 0.8), Node("b", "Б", ["kw2"], 0.5)]

    def handler(request):
        return httpx.Response(200, content=_rss(link="https://ex.com/shared"))

    summary = gnews.collect(nodes, db, client=_client(handler))
    assert items.count_items(db) == 1
    assert summary.fetched == 2
    assert summary.new == 1
    assert summary.deduped == 1
