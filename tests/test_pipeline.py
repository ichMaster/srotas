"""SROTAS-011 — backfill NULL embeddings + the collect → embed → score pass.

Guardian HTTP and Voyage embeddings are both mocked; never a paid/network call.
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


def test_run_pass_is_collect_embed_score(tmp_path):
    model_file = tmp_path / "model.yaml"
    model_file.write_text(MODEL, encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(CONFIG, encoding="utf-8")
    db = tmp_path / "items.sqlite"

    def guardian_handler(request):
        return httpx.Response(
            200,
            json={
                "response": {
                    "results": [
                        {
                            "webUrl": "https://x/a",
                            "webTitle": "A",
                            "webPublicationDate": "2026-07-01T00:00:00Z",
                            "fields": {"trailText": "t"},
                        }
                    ]
                }
            },
        )

    g_client = httpx.Client(transport=httpx.MockTransport(guardian_handler))
    summary = pipeline.run_pass(
        config_path=config_file,
        model_path=model_file,
        db_path=db,
        guardian_client=g_client,
        embed_fn=_embedder([]),
    )

    assert summary.collected.new == 1  # one article collected
    assert summary.embedded == 1  # embedded on the same pass
    assert summary.scored == 1  # and scored against the model
