"""SROTAS-010 — scoring: centroids, the cosine-only gate, ×weight ranking.

Item vectors are seeded directly into the cache; node centroids come from an
injected mock embedder. No paid API or network.
"""

import sqlite3

from core import embeddings, items, scoring
from core.model import Node


def _seed(db, url, vec, title="T", summary="s"):
    items.upsert(db, items.Item(url, "guardian", title, summary))
    items.set_embedding(db, url, embeddings.to_blob(vec))


def _embedder(mapping):
    """A mock embedder mapping each keyword string to a fixed vector."""

    def _embed(texts, input_type, api_key, *, client=None):
        assert input_type == "query"  # centroids are embedded as query
        return [mapping[t] for t in texts]

    return _embed


def _scores(db):
    conn = sqlite3.connect(db)
    try:
        return {
            u: (s, t)
            for u, s, t in conn.execute("SELECT url, score, top_node FROM items")
        }
    finally:
        conn.close()


def test_cosine_identical_orthogonal_and_zero():
    assert abs(scoring.cosine([1.0, 0.0], [1.0, 0.0]) - 1.0) < 1e-9
    assert abs(scoring.cosine([1.0, 0.0], [0.0, 1.0]) - 0.0) < 1e-9
    assert scoring.cosine([0.0, 0.0], [1.0, 1.0]) == 0.0


def test_node_centroid_is_keyword_mean():
    emb = _embedder({"k1": [2.0, 0.0], "k2": [0.0, 4.0]})
    cents = scoring.node_centroids([Node("A", "А", ["k1", "k2"], 0.5)], embed_fn=emb)
    assert cents["A"] == [1.0, 2.0]


def test_score_is_argmax_of_cosine_times_weight(tmp_path):
    db = tmp_path / "items.sqlite"
    _seed(db, "uX", [1.0, 0.0])
    _seed(db, "uY", [0.0, 1.0])
    nodes = [Node("A", "А", ["ka"], 0.9), Node("B", "Б", ["kb"], 0.1)]
    emb = _embedder({"ka": [1.0, 0.0], "kb": [0.0, 1.0]})

    n = scoring.score_items(db, nodes, threshold=0.35, embed_fn=emb)
    assert n == 2
    s = _scores(db)
    assert s["uX"][1] == "A" and abs(s["uX"][0] - 0.9) < 1e-9  # 1.0 × 0.9
    assert s["uY"][1] == "B" and abs(s["uY"][0] - 0.1) < 1e-9  # 1.0 × 0.1


def test_gate_is_cosine_only_low_weight_still_surfaces(tmp_path):
    """Contract: a low-weight node with a high cosine still surfaces the item —
    eligibility uses the pure cosine, never cosine×weight."""
    db = tmp_path / "items.sqlite"
    _seed(db, "u", [1.0, 0.0])
    # 'low' has the minimum weight but a perfect cosine; 'high' has a big weight
    # but zero cosine → ineligible.
    nodes = [Node("low", "Н", ["kl"], 0.05), Node("high", "В", ["kh"], 1.0)]
    emb = _embedder({"kl": [1.0, 0.0], "kh": [0.0, 1.0]})

    scoring.score_items(db, nodes, threshold=0.35, embed_fn=emb)
    score, top = _scores(db)["u"]
    assert top == "low"  # surfaced despite weight 0.05 (weighted score only 0.05)
    assert abs(score - 0.05) < 1e-9


def test_item_below_gate_everywhere_gets_no_top_node(tmp_path):
    db = tmp_path / "items.sqlite"
    _seed(db, "uZ", [0.0, 1.0])
    nodes = [Node("A", "А", ["ka"], 0.9)]
    emb = _embedder({"ka": [1.0, 0.0]})  # cosine 0 < 0.35

    n = scoring.score_items(db, nodes, threshold=0.35, embed_fn=emb)
    assert n == 0
    assert _scores(db)["uZ"] == (None, None)


def test_weight_reorders_but_never_changes_eligibility(tmp_path):
    db = tmp_path / "items.sqlite"
    _seed(db, "u", [1.0, 1.0])  # cosine ≈0.707 to both [1,0] and [0,1]
    emb = _embedder({"ka": [1.0, 0.0], "kb": [0.0, 1.0]})

    scoring.score_items(
        db,
        [Node("A", "А", ["ka"], 0.5), Node("B", "Б", ["kb"], 0.9)],
        threshold=0.35,
        embed_fn=emb,
    )
    assert _scores(db)["u"][1] == "B"  # 0.707×0.9 > 0.707×0.5

    # Flip the weights: A now wins, but both nodes stay eligible (gate unchanged).
    n = scoring.score_items(
        db,
        [Node("A", "А", ["ka"], 0.9), Node("B", "Б", ["kb"], 0.5)],
        threshold=0.35,
        embed_fn=emb,
    )
    assert n == 1
    assert _scores(db)["u"][1] == "A"
