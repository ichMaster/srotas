"""SROTAS-024 — the browser history adapter.

Reads a **copy** of the browser's history database — Chrome's `History` or
Firefox's `places.sqlite`; both hold their history in SQLite and are locked
while the browser runs, so this always operates on a snapshot copy taken via
`sqlite3 .backup` (WAL-safe), never the live file (ARCHITECTURE §Bootstrap,
MISSION decision 27) — and extracts visited page titles + domains as text
units.

Schema auto-detected via `sqlite_master` — confirmed against a real Chrome
profile: `urls(id, url, title, visit_count, typed_count, last_visit_time,
hidden)`. Firefox's `places.sqlite` uses `moz_places(id, url, title, ...)`
with the same two columns of interest.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from bootstrap.units import TextUnit

# table -> the (url, title) query for that browser's schema.
_SCHEMAS = {
    "urls": "SELECT url, title FROM urls",  # Chrome
    "moz_places": "SELECT url, title FROM moz_places",  # Firefox
}


def _domain(url: str) -> str:
    return urlparse(url).netloc


def read_units(path: str | Path) -> list[TextUnit]:
    """Parse a browser history snapshot into title/domain text units.

    Raises ``FileNotFoundError`` if the snapshot is missing and ``ValueError``
    if neither a Chrome nor a Firefox history table is found — fails loudly
    rather than silently returning nothing.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Browser history snapshot not found: {p}")

    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        query = next((q for table, q in _SCHEMAS.items() if table in tables), None)
        if query is None:
            raise ValueError(
                f"{p} has neither a Chrome ('urls') nor a Firefox ('moz_places') "
                "history table"
            )
        rows = conn.execute(query).fetchall()
    finally:
        conn.close()

    units: list[TextUnit] = []
    for url, title in rows:
        if not title:
            continue
        text = f"{title} — {_domain(url)}"
        units.append(TextUnit(source="browser_history", text=text))
    return units
