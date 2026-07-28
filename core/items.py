"""SROTAS-006 — the item store (``items.sqlite``).

Collectors normalize every source into an :class:`Item`; this module owns the
store the items land in. The **items schema is a contract that must not drift**
(ARCHITECTURE §Item store, §Contracts)::

    items(url PRIMARY KEY, source, title, summary,
          published_at, first_seen,
          embedding BLOB, score REAL, top_node TEXT)

Deduplication is by **URL only** — no simhash (that is stage 6). ``published_at``
is **nullable** (not every source dates its items; the feed falls back to
``first_seen``). The full column set is created now; this phase populates only
the collected fields and leaves ``embedding``/``score``/``top_node`` NULL for
phase 0.3 to fill. ``items.sqlite`` runs in WAL mode so the scheduler thread and
web requests can share it within the one process; it is runtime data
(gitignored).
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# The item store lives at the repo root (runtime data, gitignored).
DEFAULT_ITEMS_DB = Path("items.sqlite")

# The nine columns are the contract; the collector fills the first five, the
# store stamps first_seen, and phase 0.3 fills embedding/score/top_node.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    url          TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    title        TEXT NOT NULL,
    summary      TEXT,
    published_at TEXT,
    first_seen   TEXT NOT NULL,
    embedding    BLOB,
    score        REAL,
    top_node     TEXT
);
"""


@dataclass(frozen=True)
class Item:
    """One collected article. ``published_at`` is nullable (undated sources).

    The store owns ``first_seen`` and the derived ``embedding``/``score``/
    ``top_node`` columns; the collector only produces the fields below.
    """

    url: str
    source: str
    title: str
    summary: str | None = None
    published_at: str | None = None


def _connect(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating parent dirs), enable WAL, and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute(_SCHEMA)
    return conn


def init_db(db_path: str | Path = DEFAULT_ITEMS_DB) -> Path:
    """Create ``items.sqlite`` (WAL + schema) if absent; return its path."""
    with _connect(db_path) as conn:
        conn.commit()
    return Path(db_path)


def upsert(db_path: str | Path, item: Item, *, ts: str | None = None) -> bool:
    """Insert ``item`` or update the existing row for its URL; dedup by URL.

    Returns ``True`` when a new row was created, ``False`` when an existing URL
    was updated (so a caller can report new/deduped counts). On update only the
    collected fields change — ``first_seen`` is preserved from the first insert,
    and ``embedding``/``score``/``top_node`` are left untouched so a re-collect
    never clobbers phase 0.3's cached vectors. ``ts`` overrides ``first_seen``
    for deterministic tests; it defaults to the current UTC time.
    """
    when = ts if ts is not None else datetime.now(UTC).isoformat()
    with _connect(db_path) as conn:
        existed = conn.execute(
            "SELECT 1 FROM items WHERE url = ?", (item.url,)
        ).fetchone()
        conn.execute(
            """
            INSERT INTO items (url, source, title, summary, published_at, first_seen)
            VALUES (:url, :source, :title, :summary, :published_at, :first_seen)
            ON CONFLICT(url) DO UPDATE SET
                source       = excluded.source,
                title        = excluded.title,
                summary      = excluded.summary,
                published_at = excluded.published_at
            """,
            {
                "url": item.url,
                "source": item.source,
                "title": item.title,
                "summary": item.summary,
                "published_at": item.published_at,
                "first_seen": when,
            },
        )
        conn.commit()
    return existed is None


def read_items(db_path: str | Path = DEFAULT_ITEMS_DB) -> list[Item]:
    """Read the collected fields of every item, oldest ``first_seen`` first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, source, title, summary, published_at "
            "FROM items ORDER BY first_seen, url"
        ).fetchall()
    return [
        Item(
            url=row["url"],
            source=row["source"],
            title=row["title"],
            summary=row["summary"],
            published_at=row["published_at"],
        )
        for row in rows
    ]


def count_items(db_path: str | Path = DEFAULT_ITEMS_DB) -> int:
    """Number of rows in the store."""
    with _connect(db_path) as conn:
        return int(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0])


# --- Embedding cache (SROTAS-009) -----------------------------------------
# The embedding BLOB is the Voyage vector cache; the store keeps the bytes, the
# embedder (core/embeddings.py) owns the vector<->bytes serialization.


def read_unembedded(db_path: str | Path = DEFAULT_ITEMS_DB) -> list[Item]:
    """Items whose ``embedding`` is still NULL, oldest ``first_seen`` first."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, source, title, summary, published_at "
            "FROM items WHERE embedding IS NULL ORDER BY first_seen, url"
        ).fetchall()
    return [
        Item(
            url=row["url"],
            source=row["source"],
            title=row["title"],
            summary=row["summary"],
            published_at=row["published_at"],
        )
        for row in rows
    ]


def set_embedding(db_path: str | Path, url: str, blob: bytes) -> None:
    """Cache one item's embedding BLOB, keyed on URL."""
    with _connect(db_path) as conn:
        conn.execute("UPDATE items SET embedding = ? WHERE url = ?", (blob, url))
        conn.commit()


def get_embedding(db_path: str | Path, url: str) -> bytes | None:
    """Read one item's cached embedding BLOB (``None`` if unset/absent)."""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT embedding FROM items WHERE url = ?", (url,)
        ).fetchone()
    return row["embedding"] if row else None


# --- Scoring accessors (SROTAS-010) ---------------------------------------


def read_embedded(db_path: str | Path = DEFAULT_ITEMS_DB) -> list[tuple[Item, bytes]]:
    """Items that already have a cached embedding, paired with the raw BLOB."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, source, title, summary, published_at, embedding "
            "FROM items WHERE embedding IS NOT NULL ORDER BY first_seen, url"
        ).fetchall()
    return [
        (
            Item(
                url=row["url"],
                source=row["source"],
                title=row["title"],
                summary=row["summary"],
                published_at=row["published_at"],
            ),
            row["embedding"],
        )
        for row in rows
    ]


def set_score(
    db_path: str | Path, url: str, score: float | None, top_node: str | None
) -> None:
    """Write a scoring pass's ``score`` + ``top_node`` for one item (NULLs clear
    an item that no longer clears the gate)."""
    with _connect(db_path) as conn:
        conn.execute(
            "UPDATE items SET score = ?, top_node = ? WHERE url = ?",
            (score, top_node, url),
        )
        conn.commit()


def read_top_scored(
    db_path: str | Path = DEFAULT_ITEMS_DB, limit: int = 20
) -> list[tuple[str, str, str, float, str]]:
    """The top ``limit`` scored items (``top_node`` set), highest score first.

    Each row is ``(url, source, title, score, top_node)``."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, source, title, score, top_node FROM items "
            "WHERE top_node IS NOT NULL ORDER BY score DESC, url LIMIT ?",
            (limit,),
        ).fetchall()
    return [
        (row["url"], row["source"], row["title"], row["score"], row["top_node"])
        for row in rows
    ]
