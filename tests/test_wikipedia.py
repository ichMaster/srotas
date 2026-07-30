"""SROTAS-019 — Wikipedia collector: one search request per node, the daily
featured feed, and the expected field mapping (published_at always None). All
HTTP is mocked via httpx.MockTransport; never a live or paid call.
"""

from datetime import date

import httpx

from collectors import wikipedia
from core import items
from core.model import Node


def _search_response(pages):
    return {"pages": pages}


def _page(key, title="T", excerpt="excerpt text"):
    return {"key": key, "title": title, "excerpt": excerpt}


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_normalize_maps_search_result_fields():
    item = wikipedia.normalize(_page("Some_Article", "Some Article", "A summary"))
    assert item.url == "https://en.wikipedia.org/wiki/Some_Article"
    assert item.source == "wikipedia"
    assert item.title == "Some Article"
    assert item.summary == "A summary"
    assert item.published_at is None  # Wikipedia has no publication date


def test_normalize_featured_uses_extract_when_no_excerpt():
    tfa = {"key": "Today", "title": "Today's Article", "extract": "extract text"}
    item = wikipedia.normalize(tfa)
    assert item.summary == "extract text"


def test_build_query_or_joins_keywords():
    node = Node("n", "Н", ["quantum physics", "entanglement"], 0.5)
    assert wikipedia.build_query(node) == '"quantum physics" OR "entanglement"'


def test_one_search_request_per_node_with_or_query(tmp_path):
    nodes = [
        Node("a", "А", ["alpha one", "alpha two"], 0.8),
        Node("b", "Б", ["beta"], 0.5),
    ]
    seen = []

    def handler(request):
        if "/search/page" in str(request.url):
            seen.append(request)
            return httpx.Response(200, json=_search_response([]))
        return httpx.Response(200, json={})  # featured call — no article today

    wikipedia.collect(
        nodes,
        tmp_path / "items.sqlite",
        client=_client(handler),
        today=date(2026, 7, 30),
    )

    assert len(seen) == 2  # one search request per node, not per keyword
    assert seen[0].url.params["q"] == '"alpha one" OR "alpha two"'
    assert seen[1].url.params["q"] == '"beta"'


def test_collect_writes_search_and_featured_items(tmp_path):
    db = tmp_path / "items.sqlite"
    node = Node("a", "А", ["kw"], 0.8)

    def handler(request):
        if "/search/page" in str(request.url):
            return httpx.Response(
                200, json=_search_response([_page("Search_Hit", "Search Hit")])
            )
        return httpx.Response(
            200,
            json={
                "tfa": {
                    "key": "Featured_Today",
                    "title": "Featured Today",
                    "extract": "today's pick",
                }
            },
        )

    summary = wikipedia.collect(
        [node], db, client=_client(handler), today=date(2026, 7, 30)
    )
    assert summary.new == 2  # one search hit + one featured article
    stored = {it.url: it for it in items.read_items(db)}
    assert "https://en.wikipedia.org/wiki/Search_Hit" in stored
    assert "https://en.wikipedia.org/wiki/Featured_Today" in stored
    assert stored["https://en.wikipedia.org/wiki/Featured_Today"].summary == (
        "today's pick"
    )
    assert all(it.published_at is None for it in stored.values())


def test_featured_requests_the_given_date():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        return httpx.Response(200, json={})

    wikipedia.featured(client=_client(handler), today=date(2026, 7, 30))
    assert seen["url"].endswith("/feed/featured/2026/07/30")


def test_featured_absent_yields_no_items():
    def handler(request):
        return httpx.Response(200, json={})  # no "tfa" key today

    result = wikipedia.featured(client=_client(handler), today=date(2026, 7, 30))
    assert result == []


def test_same_url_across_node_and_featured_dedups_to_one_row(tmp_path):
    """URL dedup carries through: the featured article also matching a node's
    search still yields a single row."""
    db = tmp_path / "items.sqlite"
    node = Node("a", "А", ["kw"], 0.8)
    shared = _page("Shared_Article", "Shared Article")

    def handler(request):
        if "/search/page" in str(request.url):
            return httpx.Response(200, json=_search_response([shared]))
        return httpx.Response(
            200, json={"tfa": {**shared, "extract": "featured too"}}
        )

    summary = wikipedia.collect(
        [node], db, client=_client(handler), today=date(2026, 7, 30)
    )
    assert items.count_items(db) == 1
    assert summary.fetched == 2
    assert summary.new == 1
    assert summary.deduped == 1
