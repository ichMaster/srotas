"""SROTAS-018 — POST /feedback: classify → apply → re-score → reorder.

FastAPI TestClient; the classifier, scorer, and config are injected/monkeypatched
so nothing paid or networked ever runs.
"""

from core import config, feedback, items, model, pending_topics
from web import app as webapp

MODEL_FIXTURE = """\
- id: alpha
  label: "Альфа"
  keywords: [one]
  weight: 0.60
- id: beta
  label: "Бета"
  keywords: [two]
  weight: 0.50
"""

FAKE_CFG = config.Config(
    guardian_api_key="g",
    anthropic_api_key="a",
    voyage_api_key="v",
    cosine_threshold=0.35,
    feedback_like_delta=0.05,
    feedback_dislike_delta=-0.07,
)


def _setup(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    items.upsert(db, items.Item("https://ex.com/a", "guardian", "Title", "s"))
    items.set_score(db, "https://ex.com/a", 0.30, "alpha")

    model_path = tmp_path / "model.yaml"
    model_path.write_text(MODEL_FIXTURE, encoding="utf-8")
    events_db = tmp_path / "events.sqlite"
    pending_path = tmp_path / "pending_topics.yaml"

    monkeypatch.setattr(webapp, "DB_PATH", db)
    monkeypatch.setattr(webapp, "MODEL_PATH", model_path)
    monkeypatch.setattr(webapp, "EVENTS_DB", events_db)
    monkeypatch.setattr(webapp, "PENDING_TOPICS_PATH", pending_path)
    monkeypatch.setattr(webapp.config, "load_config", lambda: FAKE_CFG)
    return db, model_path, events_db, pending_path


def _client():
    from fastapi.testclient import TestClient

    return TestClient(webapp.app)


def test_like_raises_weight_and_updates_score(tmp_path, monkeypatch):
    db, model_path, events_db, _ = _setup(tmp_path, monkeypatch)

    monkeypatch.setattr(
        webapp.feedback,
        "classify",
        lambda text, title, top_node, api_key: feedback.Classification("like"),
    )
    score_calls = []

    def fake_score_items(
        db_path, nodes, *, threshold, api_key, client=None, embed_fn=None
    ):
        score_calls.append({"nodes": [n.id for n in nodes], "threshold": threshold})
        items.set_score(db_path, "https://ex.com/a", 0.99, "alpha")
        return 1

    monkeypatch.setattr(webapp.scoring, "score_items", fake_score_items)

    resp = _client().post(
        "/feedback",
        data={
            "url": "https://ex.com/a",
            "title": "Title",
            "top_node": "alpha",
            "text": "love it",
        },
    )
    assert resp.status_code == 200

    reloaded = {n.id: n.weight for n in model.load_model(model_path)}
    assert abs(reloaded["alpha"] - 0.65) < 1e-9  # 0.60 + like delta

    (scored,) = [it for it in items.read_feed(db) if it.url == "https://ex.com/a"]
    assert abs(scored.score - 0.99) < 1e-9  # re-score wrote the new score

    assert len(score_calls) == 1
    assert score_calls[0]["threshold"] == 0.35
    assert "alpha" in score_calls[0]["nodes"] and "beta" in score_calls[0]["nodes"]


def test_dislike_lowers_weight(tmp_path, monkeypatch):
    _, model_path, _, _ = _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        webapp.feedback,
        "classify",
        lambda text, title, top_node, api_key: feedback.Classification("dislike"),
    )
    monkeypatch.setattr(
        webapp.scoring, "score_items", lambda *a, **k: 0
    )

    resp = _client().post(
        "/feedback",
        data={
            "url": "https://ex.com/a",
            "title": "Title",
            "top_node": "alpha",
            "text": "meh",
        },
    )
    assert resp.status_code == 200
    reloaded = {n.id: n.weight for n in model.load_model(model_path)}
    assert abs(reloaded["alpha"] - 0.53) < 1e-9  # 0.60 - 0.07


def test_new_topic_leaves_model_untouched_and_queues(tmp_path, monkeypatch):
    _, model_path, _, pending_path = _setup(tmp_path, monkeypatch)
    before = model_path.read_text(encoding="utf-8")

    monkeypatch.setattr(
        webapp.feedback,
        "classify",
        lambda text, title, top_node, api_key: feedback.Classification(
            "new_topic", "quantum computing"
        ),
    )
    score_calls = []
    monkeypatch.setattr(
        webapp.scoring, "score_items", lambda *a, **k: score_calls.append(1)
    )

    resp = _client().post(
        "/feedback",
        data={
            "url": "https://ex.com/a",
            "title": "Title",
            "top_node": "alpha",
            "text": "more about quantum stuff",
        },
    )
    assert resp.status_code == 200
    assert model_path.read_text(encoding="utf-8") == before  # untouched
    assert score_calls == []  # no weight change → no re-score

    topics = pending_topics.read_topics(pending_path)
    assert len(topics) == 1
    assert topics[0]["hint"] == "quantum computing"


def test_card_feedback_field_is_no_longer_inert(tmp_path, monkeypatch):
    db, _, _, _ = _setup(tmp_path, monkeypatch)
    body = _client().get("/").text
    assert 'hx-post="/feedback"' in body
    assert "disabled" not in body


# --- inline acknowledgement (own-card swap, not a full re-render) ---


def test_post_feedback_returns_a_small_inline_fragment_not_the_whole_page(
    tmp_path, monkeypatch
):
    """The response replaces just the card's form — it is not a full HTML page
    (no re-render/reorder of the rest of the feed on submit)."""
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        webapp.feedback,
        "classify",
        lambda text, title, top_node, api_key: feedback.Classification("like"),
    )
    monkeypatch.setattr(webapp.scoring, "score_items", lambda *a, **k: 1)

    resp = _client().post(
        "/feedback",
        data={
            "url": "https://ex.com/a",
            "title": "Title",
            "top_node": "alpha",
            "text": "love it",
        },
    )
    assert resp.status_code == 200
    assert "<!doctype html>" not in resp.text.lower()  # a fragment, not a page
    assert "Вподобано" in resp.text
    assert "0.60" in resp.text and "0.65" in resp.text  # old → new weight
    assert "оновити фід" in resp.text


def test_new_topic_ack_has_no_weight_change_shown(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        webapp.feedback,
        "classify",
        lambda text, title, top_node, api_key: feedback.Classification(
            "new_topic", "quantum computing"
        ),
    )
    monkeypatch.setattr(
        webapp.scoring, "score_items", lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("new_topic must not trigger a re-score")
        )
    )

    resp = _client().post(
        "/feedback",
        data={
            "url": "https://ex.com/a",
            "title": "Title",
            "top_node": "alpha",
            "text": "more about quantum stuff",
        },
    )
    assert resp.status_code == 200
    assert "чергу" in resp.text
    assert "→" not in resp.text.split("оновити")[0]  # no "old → new" weight shown


# --- persisted "already reacted" state (survives reload / filtering) ---


def test_already_reacted_card_shows_ack_instead_of_form_on_plain_get(
    tmp_path, monkeypatch
):
    """A prior reaction, recorded only in events.sqlite (no in-page state),
    still shows as acknowledged on a fresh GET / — the concern being that the
    confirmation must not depend on ephemeral page state that a reload loses."""
    _, model_path, events_db, _ = _setup(tmp_path, monkeypatch)
    feedback.apply_reaction(
        "like",
        "alpha",
        "https://ex.com/a",
        "love it",
        model_path=model_path,
        events_db=events_db,
    )

    body = _client().get("/").text
    assert "Вподобано" in body
    # the form for this item is gone — replaced by the persisted ack
    assert 'value="https://ex.com/a"' not in body


def test_already_reacted_state_survives_a_node_filter_navigation(
    tmp_path, monkeypatch
):
    """The persisted ack still shows when the same card is reached through a
    node-tag filter (a full page GET, not an HTMX swap)."""
    _, model_path, events_db, _ = _setup(tmp_path, monkeypatch)
    feedback.apply_reaction(
        "like",
        "alpha",
        "https://ex.com/a",
        "love it",
        model_path=model_path,
        events_db=events_db,
    )

    body = _client().get("/?node=alpha").text
    assert "Вподобано" in body


def test_feedback_event_payload_carries_the_reaction(tmp_path, monkeypatch):
    from core import events as events_module

    _, model_path, events_db, _ = _setup(tmp_path, monkeypatch)
    feedback.apply_reaction(
        "dislike",
        "alpha",
        "https://ex.com/a",
        "meh",
        model_path=model_path,
        events_db=events_db,
    )
    fb = events_module.read_events(events_db, kind="feedback")[0]
    assert fb.payload["reaction"] == "dislike"

    latest = events_module.latest_feedback_by_url(events_db)
    assert latest["https://ex.com/a"]["reaction"] == "dislike"
    assert abs(latest["https://ex.com/a"]["old_weight"] - 0.60) < 1e-9
    assert abs(latest["https://ex.com/a"]["new_weight"] - 0.53) < 1e-9
