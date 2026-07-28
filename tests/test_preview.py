"""SROTAS-012 — CLI preview: top-N by descending score, threshold honored.

Item vectors are seeded into the cache; node centroids come from a mock
embedder. No paid API or network.
"""

from core import embeddings, items, scoring
from core.model import Node


def _seed(db, url, vec, title):
    items.upsert(db, items.Item(url, "guardian", title, "s"))
    items.set_embedding(db, url, embeddings.to_blob(vec))


def _embedder(mapping):
    def _embed(texts, input_type, api_key, *, client=None):
        return [mapping[t] for t in texts]

    return _embed


def _fixture(tmp_path):
    db = tmp_path / "items.sqlite"
    _seed(db, "uHigh", [1.0, 0.0], "High")  # cosine 1.0 to node A
    _seed(db, "uMid", [0.6, 0.8], "Mid")  # cosine 0.6 to node A
    _seed(db, "uLow", [0.2, 0.98], "Low")  # cosine 0.2 — below 0.35
    nodes = [Node("A", "А", ["ka"], 1.0)]
    emb = _embedder({"ka": [1.0, 0.0]})
    return db, nodes, emb


def test_preview_orders_by_score_desc_and_excludes_below_threshold(tmp_path):
    db, nodes, emb = _fixture(tmp_path)
    rows = scoring.preview(db, nodes, threshold=0.35, top_n=20, embed_fn=emb)

    assert [r.url for r in rows] == ["uHigh", "uMid"]  # uLow gated out
    assert rows[0].score > rows[1].score  # descending
    assert abs(rows[0].cosine - 1.0) < 1e-6
    assert abs(rows[1].cosine - 0.6) < 1e-6
    assert all(r.top_node == "A" for r in rows)


def test_preview_respects_a_raised_threshold(tmp_path):
    db, nodes, emb = _fixture(tmp_path)
    rows = scoring.preview(db, nodes, threshold=0.7, top_n=20, embed_fn=emb)
    assert [r.url for r in rows] == ["uHigh"]  # uMid (0.6) now excluded too


def test_preview_top_n_caps_the_list(tmp_path):
    db, nodes, emb = _fixture(tmp_path)
    rows = scoring.preview(db, nodes, threshold=0.35, top_n=1, embed_fn=emb)
    assert len(rows) == 1
    assert rows[0].url == "uHigh"


def test_format_preview_has_header_and_titles(tmp_path):
    db, nodes, emb = _fixture(tmp_path)
    rows = scoring.preview(db, nodes, threshold=0.35, embed_fn=emb)
    text = scoring.format_preview(rows)
    assert "score" in text and "top_node" in text
    assert "High" in text and "Mid" in text


def test_format_preview_empty():
    assert "no items" in scoring.format_preview([])
