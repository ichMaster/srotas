"""SROTAS-006 — item store: 9-column schema contract + URL-dedup upsert.

All against a temp DB; no paid API or network.
"""

import sqlite3

from core import items

# The items schema is a contract that must not drift (ARCHITECTURE §Item store).
EXPECTED_COLUMNS = [
    "url",
    "source",
    "title",
    "summary",
    "published_at",
    "first_seen",
    "embedding",
    "score",
    "top_node",
]


def _db(tmp_path):
    return tmp_path / "items.sqlite"


def test_init_creates_wal_db(tmp_path):
    path = items.init_db(_db(tmp_path))
    assert path.exists()
    conn = sqlite3.connect(path)
    try:
        mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
    finally:
        conn.close()
    assert mode.lower() == "wal"


def test_schema_is_the_nine_columns_contract(tmp_path):
    """Contract: exactly 9 columns, url PRIMARY KEY, published_at nullable."""
    path = items.init_db(_db(tmp_path))
    conn = sqlite3.connect(path)
    try:
        info = list(conn.execute("PRAGMA table_info(items);"))
    finally:
        conn.close()
    # PRAGMA row: (cid, name, type, notnull, dflt_value, pk)
    assert [row[1] for row in info] == EXPECTED_COLUMNS
    by_name = {row[1]: row for row in info}
    assert by_name["url"][5] == 1  # url is the PRIMARY KEY
    assert by_name["published_at"][3] == 0  # published_at is nullable


def test_upsert_dedups_by_url(tmp_path):
    """Re-upserting the same URL updates in place — no second row."""
    db = _db(tmp_path)
    items.upsert(db, items.Item("https://ex.com/a", "guardian", "First", "s1"))
    items.upsert(db, items.Item("https://ex.com/b", "guardian", "Other", "s2"))
    assert items.count_items(db) == 2

    # Same URL, changed title → still 2 rows, title updated.
    items.upsert(
        db, items.Item("https://ex.com/a", "guardian", "First (edited)", "s1b")
    )
    assert items.count_items(db) == 2
    by_url = {it.url: it for it in items.read_items(db)}
    assert by_url["https://ex.com/a"].title == "First (edited)"
    assert by_url["https://ex.com/a"].summary == "s1b"


def test_upsert_returns_created_flag(tmp_path):
    db = _db(tmp_path)
    a = items.Item("https://ex.com/a", "guardian", "T", "s")
    a2 = items.Item("https://ex.com/a", "guardian", "T2", "s")
    assert items.upsert(db, a) is True
    assert items.upsert(db, a2) is False


def test_null_published_at_accepted(tmp_path):
    """Undated sources (e.g. Wikipedia) upsert with published_at = None."""
    db = _db(tmp_path)
    items.upsert(db, items.Item("https://ex.com/x", "wikipedia", "No date", "s", None))
    (it,) = items.read_items(db)
    assert it.published_at is None


def test_first_seen_preserved_on_update(tmp_path):
    """first_seen is stamped once, on the first insert, and never overwritten."""
    db = _db(tmp_path)
    url = "https://ex.com/a"
    items.upsert(db, items.Item(url, "guardian", "T", "s"), ts="2026-07-01")
    items.upsert(db, items.Item(url, "guardian", "T2", "s"), ts="2026-07-09")
    conn = sqlite3.connect(db)
    try:
        first_seen = conn.execute(
            "SELECT first_seen FROM items WHERE url = ?", (url,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert first_seen == "2026-07-01"


def test_derived_columns_stay_null_this_phase(tmp_path):
    """embedding/score/top_node are phase 0.3's — NULL after a collect upsert."""
    db = _db(tmp_path)
    items.upsert(db, items.Item("https://ex.com/a", "guardian", "T", "s"))
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT embedding, score, top_node FROM items WHERE url = ?",
            ("https://ex.com/a",),
        ).fetchone()
    finally:
        conn.close()
    assert row == (None, None, None)
