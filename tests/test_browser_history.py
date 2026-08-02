"""SROTAS-024 — browser history adapter: Chrome + Firefox schemas, both
producing the same TextUnit shape. Fixture DBs match the real schemas
(Chrome's urls table confirmed against a real profile snapshot). No network,
no real browser history needed.
"""

import sqlite3

import pytest

from bootstrap.browser_history import read_units


def _chrome_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE urls(id INTEGER PRIMARY KEY, url LONGVARCHAR, title LONGVARCHAR, "
        "visit_count INTEGER DEFAULT 0, typed_count INTEGER DEFAULT 0, "
        "last_visit_time INTEGER, hidden INTEGER DEFAULT 0)"
    )
    conn.executemany("INSERT INTO urls(url, title) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def _firefox_db(path, rows):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE moz_places(id INTEGER PRIMARY KEY, url TEXT, title TEXT, "
        "visit_count INTEGER DEFAULT 0, hidden INTEGER DEFAULT 0)"
    )
    conn.executemany("INSERT INTO moz_places(url, title) VALUES (?, ?)", rows)
    conn.commit()
    conn.close()


def test_chrome_schema_produces_text_units(tmp_path):
    db = tmp_path / "History"
    _chrome_db(
        db,
        [
            (
                "https://en.wikipedia.org/wiki/Quantum_entanglement",
                "Quantum entanglement",
            ),
            ("https://news.ycombinator.com/item?id=1", "Hacker News thread"),
        ],
    )
    units = read_units(db)
    assert units[0].text == "Quantum entanglement — en.wikipedia.org"
    assert units[1].text == "Hacker News thread — news.ycombinator.com"
    assert all(u.source == "browser_history" for u in units)


def test_firefox_schema_produces_the_same_shape(tmp_path):
    db = tmp_path / "places.sqlite"
    _firefox_db(db, [("https://example.com/page", "Example Page")])
    (unit,) = read_units(db)
    assert unit.text == "Example Page — example.com"
    assert unit.source == "browser_history"


def test_empty_title_rows_are_skipped(tmp_path):
    db = tmp_path / "History"
    _chrome_db(db, [("https://a.com", ""), ("https://b.com", "B title")])
    units = read_units(db)
    assert len(units) == 1
    assert units[0].text == "B title — b.com"


def test_unrecognized_schema_raises(tmp_path):
    db = tmp_path / "unknown.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE something_else(id INTEGER)")
    conn.commit()
    conn.close()
    with pytest.raises(ValueError, match="neither a Chrome"):
        read_units(db)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_units(tmp_path / "nope.sqlite")
