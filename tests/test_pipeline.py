"""SROTAS-011/021 — backfill NULL embeddings + the collect → embed → score
pass, now over all three collectors (Guardian, Wikipedia, GNews).

All collector HTTP and Voyage embeddings are mocked; never a paid/network call.
"""

import httpx

from core import embeddings, items, pipeline
from core.model import Node

# A mock embedder that returns the same vector for every text — both for item
# documents and node-keyword queries — so everything aligns to node "a".
_ALIGNED = [1.0, 0.0]


def _embedder(counter):
    def _embed(texts, input_type, api_key, *, client=None):
        counter.append(input_type)
        return [list(_ALIGNED) for _ in texts]

    return _embed


def test_backfill_embeds_only_nulls_then_scores(tmp_path):
    db = tmp_path / "items.sqlite"
    # u1 is already embedded; u2 is a NULL row.
    items.upsert(db, items.Item("u1", "guardian", "T1", "s1"))
    items.set_embedding(db, "u1", embeddings.to_blob(_ALIGNED))
    items.upsert(db, items.Item("u2", "guardian", "T2", "s2"))
    nodes = [Node("a", "А", ["ka"], 0.9)]

    seen = []
    embedded, scored = pipeline.embed_and_score(
        db, nodes, threshold=0.35, embed_fn=_embedder(seen)
    )
    assert embedded == 1  # only the NULL row (u2) was embedded
    assert scored == 2  # both items align to node "a" and clear the gate
    assert seen.count("document") == 1  # one batched document embed for u2
    assert items.get_embedding(db, "u1") is not None

    # Idempotent: a second pass embeds nothing and re-scores from the cache.
    seen.clear()
    embedded2, scored2 = pipeline.embed_and_score(
        db, nodes, threshold=0.35, embed_fn=_embedder(seen)
    )
    assert embedded2 == 0
    assert scored2 == 2
    assert seen.count("document") == 0  # no re-embedding


MODEL = """\
- id: a
  label: "А"
  keywords: [ka]
  weight: 0.9
"""

CONFIG = (
    '[guardian]\napi_key = "g"\n'
    '[voyage]\napi_key = "v"\n'
    "[scoring]\nthreshold = 0.35\n"
)


def _guardian_client(url="https://x/a", title="A"):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "response": {
                    "results": [
                        {
                            "webUrl": url,
                            "webTitle": title,
                            "webPublicationDate": "2026-07-01T00:00:00Z",
                            "fields": {"trailText": "t"},
                        }
                    ]
                }
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


def _empty_wikipedia_client():
    def handler(request):
        if "/search/page" in str(request.url):
            return httpx.Response(200, json={"pages": []})
        return httpx.Response(200, json={})  # no featured article

    return httpx.Client(transport=httpx.MockTransport(handler))


def _wikipedia_client_with_page(key="Some_Article", title="Some Article"):
    def handler(request):
        if "/search/page" in str(request.url):
            return httpx.Response(
                200, json={"pages": [{"key": key, "title": title, "excerpt": "e"}]}
            )
        return httpx.Response(200, json={})  # no featured article

    return httpx.Client(transport=httpx.MockTransport(handler))


_EMPTY_RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>"""


def _rss_item(title="T", link="https://ex.com/gnews"):
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><item>
  <title>{title}</title>
  <link>{link}</link>
  <pubDate>Wed, 30 Jul 2026 12:00:00 GMT</pubDate>
  <description>s</description>
</item></channel></rss>""".encode()


def _empty_gnews_client():
    def handler(request):
        return httpx.Response(200, content=_EMPTY_RSS)

    return httpx.Client(transport=httpx.MockTransport(handler))


def _gnews_client_with_item(title="T", link="https://ex.com/gnews"):
    def handler(request):
        return httpx.Response(200, content=_rss_item(title, link))

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_run_pass_is_collect_embed_score(tmp_path):
    model_file = tmp_path / "model.yaml"
    model_file.write_text(MODEL, encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(CONFIG, encoding="utf-8")
    db = tmp_path / "items.sqlite"

    summary = pipeline.run_pass(
        config_path=config_file,
        model_path=model_file,
        db_path=db,
        guardian_client=_guardian_client(),
        wikipedia_client=_empty_wikipedia_client(),
        gnews_client=_empty_gnews_client(),
        embed_fn=_embedder([]),
    )

    assert summary.collected["guardian"].new == 1  # one article collected
    assert summary.embedded == 1  # embedded on the same pass
    assert summary.scored == 1  # and scored against the model


def test_run_pass_collects_from_all_three_sources(tmp_path):
    model_file = tmp_path / "model.yaml"
    model_file.write_text(MODEL, encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(CONFIG, encoding="utf-8")
    db = tmp_path / "items.sqlite"

    summary = pipeline.run_pass(
        config_path=config_file,
        model_path=model_file,
        db_path=db,
        guardian_client=_guardian_client("https://x/guardian-item"),
        wikipedia_client=_wikipedia_client_with_page("Wiki_Item"),
        gnews_client=_gnews_client_with_item(link="https://x/gnews-item"),
        embed_fn=_embedder([]),
    )

    assert summary.collected["guardian"].new == 1
    assert summary.collected["wikipedia"].new == 1
    assert summary.collected["gnews"].new == 1

    stored = {it.url: it for it in items.read_items(db)}
    assert "https://x/guardian-item" in stored
    assert "https://en.wikipedia.org/wiki/Wiki_Item" in stored
    assert "https://x/gnews-item" in stored
    assert {it.source for it in stored.values()} == {"guardian", "wikipedia", "gnews"}

    # embedded + scored together, in the same pass
    assert summary.embedded == 3
    assert summary.scored == 3


def test_run_pass_dedups_the_same_url_across_sources(tmp_path):
    """The same article surfaced by two sources yields one row — URL-PK
    upsert already gives cross-source dedup for free (ARCHITECTURE §Collectors)."""
    model_file = tmp_path / "model.yaml"
    model_file.write_text(MODEL, encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(CONFIG, encoding="utf-8")
    db = tmp_path / "items.sqlite"
    shared_url = "https://x/shared-across-sources"

    pipeline.run_pass(
        config_path=config_file,
        model_path=model_file,
        db_path=db,
        guardian_client=_guardian_client(shared_url),
        wikipedia_client=_empty_wikipedia_client(),
        gnews_client=_gnews_client_with_item(link=shared_url),
        embed_fn=_embedder([]),
    )

    assert items.count_items(db) == 1
    (stored,) = items.read_items(db)
    assert stored.url == shared_url
