"""SROTAS-007 — Guardian collector: one OR-joined request per node, field
mapping, and URL dedup. All Guardian HTTP is mocked via httpx.MockTransport;
never a live or paid call.
"""

import httpx

from collectors import guardian
from core import items
from core.model import Node


def _response(results):
    return {"response": {"status": "ok", "results": results}}


def _result(url, title="T", trail="trail", date="2026-07-01T00:00:00Z"):
    return {
        "webUrl": url,
        "webTitle": title,
        "webPublicationDate": date,
        "fields": {"trailText": trail},
    }


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_normalize_maps_guardian_fields():
    item = guardian.normalize(
        _result("https://g.com/a", "Headline", "Summary", "2026-07-02T09:00:00Z")
    )
    assert item.url == "https://g.com/a"
    assert item.source == "guardian"
    assert item.title == "Headline"
    assert item.summary == "Summary"
    assert item.published_at == "2026-07-02T09:00:00Z"


def test_build_query_or_joins_keywords():
    node = Node("n", "Н", ["large language models", "AI agents"], 0.8)
    assert guardian.build_query(node) == '"large language models" OR "AI agents"'


def test_one_request_per_node_with_or_query(tmp_path):
    """Exactly one request per node; the q is the keywords OR-joined."""
    nodes = [
        Node("a", "А", ["alpha one", "alpha two"], 0.8),
        Node("b", "Б", ["beta"], 0.5),
    ]
    seen = []

    def handler(request):
        seen.append(request)
        url = f"https://g.com/{len(seen)}"
        return httpx.Response(200, json=_response([_result(url)]))

    guardian.collect(
        nodes, "KEY", tmp_path / "items.sqlite", client=_client(handler)
    )

    assert len(seen) == 2  # one request per node, not per keyword
    assert seen[0].url.params["q"] == '"alpha one" OR "alpha two"'
    assert seen[1].url.params["q"] == '"beta"'
    assert seen[0].url.params["api-key"] == "KEY"


def test_collect_writes_normalized_items(tmp_path):
    db = tmp_path / "items.sqlite"
    node = Node("a", "А", ["kw"], 0.8)

    def handler(request):
        return httpx.Response(
            200,
            json=_response(
                [
                    _result("https://g.com/a", "First", "t1"),
                    _result("https://g.com/b", "Second", "t2"),
                ]
            ),
        )

    summary = guardian.collect([node], "KEY", db, client=_client(handler))
    assert summary.new == 2
    stored = {it.url: it for it in items.read_items(db)}
    assert stored["https://g.com/a"].title == "First"
    assert stored["https://g.com/a"].source == "guardian"
    assert stored["https://g.com/a"].summary == "t1"


def test_same_url_across_two_nodes_dedups_to_one_row(tmp_path):
    """URL dedup carries through the collector: one row, counted once."""
    db = tmp_path / "items.sqlite"
    nodes = [Node("a", "А", ["kw1"], 0.8), Node("b", "Б", ["kw2"], 0.5)]

    def handler(request):
        return httpx.Response(200, json=_response([_result("https://g.com/shared")]))

    summary = guardian.collect(nodes, "KEY", db, client=_client(handler))
    assert items.count_items(db) == 1
    assert summary.fetched == 2
    assert summary.new == 1
    assert summary.deduped == 1
