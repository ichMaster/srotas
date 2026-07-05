"""SROTAS-003 — event journal: schema contract + append/read behavior.

All against a temp DB; no paid API or network.
"""

import sqlite3

import pytest

from core import events

EXPECTED_COLUMNS = {"id", "ts", "kind", "node_id", "payload"}


def _db(tmp_path):
    return tmp_path / "memory" / "events.sqlite"


def test_init_creates_wal_db(tmp_path):
    path = events.init_db(_db(tmp_path))
    assert path.exists()
    conn = sqlite3.connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_schema_is_the_five_minimal_columns(tmp_path):
    """Contract: events(id, ts, kind, node_id, payload) — never extended."""
    path = events.init_db(_db(tmp_path))
    conn = sqlite3.connect(path)
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(events);")}
    finally:
        conn.close()
    assert cols == EXPECTED_COLUMNS


def test_kind_is_restricted_to_the_three_allowed_values(tmp_path):
    """Contract: kind ∈ {bootstrap, feedback, weight_update}; a 4th is rejected."""
    db = _db(tmp_path)
    for kind in events.KINDS:
        events.append_event(db, kind, "some-node", {"text": "x"})
    with pytest.raises(ValueError):
        events.append_event(db, "obsolete", "some-node", {"text": "x"})


def test_db_check_constraint_also_blocks_bad_kinds(tmp_path):
    """The schema's CHECK is a second guard even if inserted directly."""
    path = events.init_db(_db(tmp_path))
    conn = sqlite3.connect(path)
    try:
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO events (ts, kind, node_id, payload) VALUES (?,?,?,?)",
                ("2026-07-05T00:00:00+00:00", "banana", None, "{}"),
            )
            conn.commit()
    finally:
        conn.close()


def test_append_and_read_round_trip_in_order(tmp_path):
    db = _db(tmp_path)
    id1 = events.append_event(
        db, "bootstrap", None, {"source": "lumi-facts"}, ts="2026-07-04T00:00:00+00:00"
    )
    id2 = events.append_event(
        db,
        "feedback",
        "ai-systems-development",
        {"text": "more like this", "url": "https://example.com/a"},
        ts="2026-07-05T00:00:00+00:00",
    )
    assert id1 == 1 and id2 == 2

    all_events = events.read_events(db)
    assert [e.id for e in all_events] == [1, 2]

    boot = all_events[0]
    assert boot.kind == "bootstrap"
    assert boot.node_id is None
    assert boot.payload == {"source": "lumi-facts"}

    fb = all_events[1]
    assert fb.kind == "feedback"
    assert fb.node_id == "ai-systems-development"
    assert fb.payload["url"] == "https://example.com/a"


def test_read_events_filters_by_kind(tmp_path):
    db = _db(tmp_path)
    events.append_event(db, "bootstrap", None, {"source": "lumi-facts"})
    events.append_event(db, "feedback", "n1", {"text": "a"})
    events.append_event(db, "weight_update", "n1", {"delta": 0.05})

    assert len(events.read_events(db, kind="bootstrap")) == 1
    assert len(events.read_events(db, kind="feedback")) == 1
    assert len(events.read_events(db)) == 3
