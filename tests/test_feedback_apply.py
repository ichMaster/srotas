"""SROTAS-017 — weight delta + events + pending_topics.yaml queue.

Against temp files; no paid API or network.
"""

from core import config, events, feedback, model, pending_topics

FIXTURE = """\
# keep me — a human comment
- id: alpha
  label: "Альфа"
  keywords: [one, two, three]
  weight: 0.60

- id: near-top
  label: "Топ"
  keywords: [x]
  weight: 0.97

- id: near-floor
  label: "Дно"
  keywords: [y]
  weight: 0.08
"""


def _model(tmp_path):
    p = tmp_path / "model.yaml"
    p.write_text(FIXTURE, encoding="utf-8")
    return p


def test_like_raises_weight_and_writes_events(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"

    new_weight = feedback.apply_reaction(
        "like",
        "alpha",
        "https://ex.com/a",
        "love this",
        model_path=m,
        events_db=db,
        ts="2026-07-30T00:00:00+00:00",
    )
    assert abs(new_weight - 0.65) < 1e-9  # 0.60 + 0.05
    reloaded = {n.id: n.weight for n in model.load_model(m)}
    assert abs(reloaded["alpha"] - 0.65) < 1e-9

    all_events = events.read_events(db)
    assert [e.kind for e in all_events] == ["feedback", "weight_update"]
    fb, wu = all_events
    assert fb.node_id == "alpha"
    assert fb.payload == {"text": "love this", "url": "https://ex.com/a"}
    assert wu.node_id == "alpha"
    assert abs(wu.payload["delta"] - 0.05) < 1e-9
    assert abs(wu.payload["old_weight"] - 0.60) < 1e-9
    assert abs(wu.payload["new_weight"] - 0.65) < 1e-9


def test_dislike_lowers_weight(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    new_weight = feedback.apply_reaction(
        "dislike", "alpha", "https://ex.com/a", "meh", model_path=m, events_db=db
    )
    assert abs(new_weight - 0.53) < 1e-9  # 0.60 - 0.07


def test_like_clamps_at_ceiling(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    new_weight = feedback.apply_reaction(
        "like", "near-top", "https://ex.com/a", "x", model_path=m, events_db=db
    )
    assert new_weight == 1.0  # 0.97 + 0.05 clamps to WEIGHT_MAX


def test_dislike_clamps_at_floor(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    new_weight = feedback.apply_reaction(
        "dislike", "near-floor", "https://ex.com/a", "x", model_path=m, events_db=db
    )
    assert new_weight == 0.05  # 0.08 - 0.07 clamps to WEIGHT_MIN


def test_model_yaml_comment_and_other_nodes_survive(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    feedback.apply_reaction(
        "like", "alpha", "https://ex.com/a", "x", model_path=m, events_db=db
    )
    text = m.read_text(encoding="utf-8")
    assert "# keep me — a human comment" in text
    assert 'label: "Альфа"' in text
    assert "weight: 0.97" in text  # near-top untouched


def test_custom_deltas_from_config(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    new_weight = feedback.apply_reaction(
        "like",
        "alpha",
        "https://ex.com/a",
        "x",
        model_path=m,
        events_db=db,
        like_delta=0.2,
    )
    assert abs(new_weight - 0.80) < 1e-9


def test_new_topic_never_touches_model_yaml(tmp_path):
    m = _model(tmp_path)
    db = tmp_path / "events.sqlite"
    ptopics = tmp_path / "pending_topics.yaml"
    before = m.read_text(encoding="utf-8")

    result = feedback.apply_reaction(
        "new_topic",
        None,
        "https://ex.com/quantum",
        "more about quantum stuff",
        topic_hint="quantum computing, qubits",
        model_path=m,
        events_db=db,
        pending_topics_path=ptopics,
        ts="2026-07-30T00:00:00+00:00",
    )
    assert result is None
    assert m.read_text(encoding="utf-8") == before  # byte-for-byte untouched

    topics = pending_topics.read_topics(ptopics)
    assert len(topics) == 1
    assert topics[0]["hint"] == "quantum computing, qubits"
    assert topics[0]["url"] == "https://ex.com/quantum"
    assert topics[0]["text"] == "more about quantum stuff"

    fb = events.read_events(db, kind="feedback")[0]
    assert fb.node_id is None
    assert fb.payload["topic_hint"] == "quantum computing, qubits"


def test_pending_topics_queue_appends_without_clobbering(tmp_path):
    p = tmp_path / "pending_topics.yaml"
    pending_topics.append_topic(p, "hint one", "u1", "t1", ts="2026-07-01")
    pending_topics.append_topic(p, "hint two", "u2", "t2", ts="2026-07-02")
    topics = pending_topics.read_topics(p)
    assert [t["hint"] for t in topics] == ["hint one", "hint two"]


def test_pending_topics_read_missing_file_is_empty(tmp_path):
    assert pending_topics.read_topics(tmp_path / "nope.yaml") == []


def test_config_reads_feedback_deltas(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[guardian]\napi_key = "g"\n'
        "[feedback]\nlike_delta = 0.1\ndislike_delta = -0.2\n",
        encoding="utf-8",
    )
    cfg = config.load_config(p)
    assert cfg.feedback_like_delta == 0.1
    assert cfg.feedback_dislike_delta == -0.2


def test_config_feedback_deltas_default(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[guardian]\napi_key = "g"\n', encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg.feedback_like_delta == 0.05
    assert cfg.feedback_dislike_delta == -0.07
