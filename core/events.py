"""SROTAS-003 — the event journal (``memory/events.sqlite``).

An append-only journal recording every model-affecting action so any weight
change is traceable to a specific feedback (MISSION §Principles — auditable).
The schema is deliberately minimal and must not be extended
(ARCHITECTURE §Contracts that must not drift)::

    events(id, ts, kind, node_id, payload)
    kind ∈ {bootstrap, feedback, weight_update}

``events.sqlite`` is runtime data (gitignored). It runs in WAL mode so the
APScheduler thread and web requests can share it within the one process.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The only kinds the journal accepts. Do not extend (MISSION §Scope, stage 2).
KINDS: tuple[str, ...] = ("bootstrap", "feedback", "weight_update")

# Default location of the event journal within the memory package.
DEFAULT_EVENTS_DB = Path("memory/events.sqlite")

# The five columns are the contract; the CHECK pins the allowed kinds in the DB.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ts      TEXT NOT NULL,
    kind    TEXT NOT NULL CHECK (kind IN ('bootstrap', 'feedback', 'weight_update')),
    node_id TEXT,
    payload TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class Event:
    """One journal row; ``payload`` is decoded back to a dict on read."""

    id: int
    ts: str
    kind: str
    node_id: str | None
    payload: dict


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating parent dirs), enable WAL, and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # WAL persists in the DB file, so later connections inherit it.
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(_SCHEMA)
    return conn


def init_db(db_path: str | Path) -> Path:
    """Create ``events.sqlite`` (WAL + schema) if absent; return its path."""
    with _connect(db_path) as conn:
        conn.commit()
    return Path(db_path)


def append_event(
    db_path: str | Path,
    kind: str,
    node_id: str | None,
    payload: Mapping | None = None,
    *,
    ts: str | None = None,
) -> int:
    """Append one event and return its row id.

    ``kind`` must be one of :data:`KINDS`; ``payload`` is JSON-encoded (the user's
    original text lives here for feedback/weight_update events). ``ts`` defaults
    to the current UTC time in ISO-8601.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; allowed: {KINDS}")
    when = ts if ts is not None else datetime.now(UTC).isoformat()
    body = json.dumps(dict(payload) if payload is not None else {})
    with _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO events (ts, kind, node_id, payload) VALUES (?, ?, ?, ?)",
            (when, kind, node_id, body),
        )
        conn.commit()
        return int(cur.lastrowid)


def read_events(db_path: str | Path, kind: str | None = None) -> list[Event]:
    """Read events in insertion order, optionally filtered to one ``kind``."""
    if kind is not None and kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; allowed: {KINDS}")
    sql = "SELECT id, ts, kind, node_id, payload FROM events"
    params: tuple = ()
    if kind is not None:
        sql += " WHERE kind = ?"
        params = (kind,)
    sql += " ORDER BY id"
    with _connect(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [
        Event(
            id=row["id"],
            ts=row["ts"],
            kind=row["kind"],
            node_id=row["node_id"],
            payload=json.loads(row["payload"]),
        )
        for row in rows
    ]


def latest_feedback_by_url(db_path: str | Path) -> dict[str, dict]:
    """The latest feedback (+ its weight change, if any) for each item URL.

    Used by the feed to show a **persisted** "already reacted" state — derived
    from the journal, not from ephemeral page state, so it survives a reload or
    a node-filter navigation (a plain page GET). Each value:
    ``{"reaction", "old_weight", "new_weight"}`` — the weight fields are
    ``None`` for ``new_topic`` (no weight change). Later feedback for the same
    URL overwrites earlier (read_events is insertion-ordered).
    """
    weight_updates = {
        (e.ts, e.node_id): e for e in read_events(db_path, kind="weight_update")
    }
    latest: dict[str, dict] = {}
    for event in read_events(db_path, kind="feedback"):
        url = event.payload.get("url")
        if not url:
            continue
        wu = weight_updates.get((event.ts, event.node_id))
        latest[url] = {
            "reaction": event.payload.get("reaction"),
            "old_weight": wu.payload.get("old_weight") if wu else None,
            "new_weight": wu.payload.get("new_weight") if wu else None,
        }
    return latest
