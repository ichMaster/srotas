"""SROTAS-009 — embedder seam (Voyage) + the item embedding cache.

All Voyage HTTP is mocked via httpx.MockTransport or an injected embed_fn; never
a paid or live call.
"""

import json

import httpx

from core import embeddings, items


def _voyage_response(n, dim=4, order=None):
    idx = order if order is not None else list(range(n))
    return {
        "object": "list",
        "model": "voyage-3",
        "data": [
            {"object": "embedding", "index": i, "embedding": [float(i)] * dim}
            for i in idx
        ],
        "usage": {"total_tokens": 1},
    }


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_embedder_seam_contract():
    """Contract: voyage-3, input_type document(items)/query(centroids), Bearer
    key, the embeddings endpoint — no LLM call. (ARCHITECTURE §Scoring, §Contracts.)
    """
    seen = {}

    def handler(request):
        body = json.loads(request.content)
        seen["input_type"] = body["input_type"]
        seen["model"] = body["model"]
        seen["input"] = body["input"]
        seen["auth"] = request.headers.get("Authorization")
        seen["url"] = str(request.url)
        return httpx.Response(200, json=_voyage_response(len(body["input"])))

    embeddings.embed(["a", "b"], "document", "VK", client=_client(handler))
    assert seen["model"] == "voyage-3"
    assert seen["input_type"] == "document"
    assert seen["input"] == ["a", "b"]
    assert seen["auth"] == "Bearer VK"
    assert seen["url"] == embeddings.VOYAGE_URL

    embeddings.embed(["c"], "query", "VK", client=_client(handler))
    assert seen["input_type"] == "query"  # centroids use query


def test_embed_returns_vectors_in_input_order():
    """Voyage may return data out of order; embed() sorts by index."""

    def handler(request):
        return httpx.Response(200, json=_voyage_response(3, order=[2, 0, 1]))

    vecs = embeddings.embed(["a", "b", "c"], "document", "VK", client=_client(handler))
    assert [v[0] for v in vecs] == [0.0, 1.0, 2.0]


def test_embed_rejects_bad_input_type():
    try:
        embeddings.embed(["a"], "sentence", "VK")
    except ValueError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for a bad input_type")


def test_embed_empty_makes_no_call():
    assert embeddings.embed([], "document", "VK") == []


def test_blob_roundtrip():
    v = [0.1, -2.5, 3.0, 4.25]
    out = embeddings.from_blob(embeddings.to_blob(v))
    assert len(out) == len(v)
    assert all(abs(a - b) < 1e-6 for a, b in zip(out, v, strict=True))


def test_item_text_is_title_dot_summary():
    with_summary = embeddings.item_text(items.Item("u", "g", "Title", "Summary"))
    assert with_summary == "Title. Summary"
    assert embeddings.item_text(items.Item("u", "g", "Title", None)) == "Title. "


def test_cache_embeds_only_uncached_then_reuses(tmp_path):
    """Embedding a batch twice calls the embedder only for the NULL rows;
    cached BLOBs decode back to the original vectors."""
    db = tmp_path / "items.sqlite"
    items.upsert(db, items.Item("u1", "guardian", "T1", "s1"))
    items.upsert(db, items.Item("u2", "guardian", "T2", "s2"))

    calls = []

    def fake(texts, input_type, api_key, *, client=None):
        calls.append((tuple(texts), input_type))
        return [[1.0, 2.0, 3.0] for _ in texts]

    n = embeddings.ensure_item_embeddings(db, "VK", embed_fn=fake)
    assert n == 2
    assert len(calls) == 1  # one batched call
    assert calls[0][1] == "document"
    assert embeddings.from_blob(items.get_embedding(db, "u1")) == [1.0, 2.0, 3.0]

    calls.clear()
    n2 = embeddings.ensure_item_embeddings(db, "VK", embed_fn=fake)
    assert n2 == 0  # nothing pending
    assert calls == []  # cache reused, embedder never called


def test_cache_embeds_only_the_new_nulls(tmp_path):
    """A row already embedded is skipped; only the fresh NULL is embedded."""
    db = tmp_path / "items.sqlite"
    items.upsert(db, items.Item("u1", "guardian", "T1", "s1"))
    calls = []

    def fake(texts, input_type, api_key, *, client=None):
        calls.append(tuple(texts))
        return [[7.0] for _ in texts]

    embeddings.ensure_item_embeddings(db, "VK", embed_fn=fake)
    items.upsert(db, items.Item("u2", "guardian", "T2", "s2"))  # a new NULL row
    calls.clear()
    n = embeddings.ensure_item_embeddings(db, "VK", embed_fn=fake)
    assert n == 1
    assert len(calls) == 1
    assert items.get_embedding(db, "u1") is not None  # u1 untouched, still cached
