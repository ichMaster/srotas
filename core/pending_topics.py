"""SROTAS-017 — the pending-topics queue (``memory/pending_topics.yaml``).

``new_topic`` feedback never creates a node automatically — the classifier
makes mistakes, and a new node immediately affects collection (new collector
queries). Instead each hint queues here for **manual confirmation**: the human
reviews the file and hand-moves a topic into ``model.yaml`` themselves; no code
path writes ``model.yaml`` from this queue (ARCHITECTURE §Feedback, §Memory
package).

Tracked in git, unlike ``events.sqlite``; reads as an empty list when the file
is absent, and is created on the first append.
"""

from __future__ import annotations

from pathlib import Path

from ruamel.yaml import YAML

DEFAULT_PENDING_TOPICS_PATH = Path("memory/pending_topics.yaml")


def _yaml() -> YAML:
    yaml = YAML()  # round-trip mode is the default
    yaml.preserve_quotes = True
    return yaml


def read_topics(path: str | Path = DEFAULT_PENDING_TOPICS_PATH) -> list[dict]:
    """Read the queue in insertion order; an absent file reads as empty."""
    p = Path(path)
    if not p.exists():
        return []
    with p.open(encoding="utf-8") as fh:
        data = _yaml().load(fh)
    return list(data) if data else []


def append_topic(
    path: str | Path,
    hint: str,
    url: str,
    text: str,
    *,
    ts: str,
) -> None:
    """Append one unconfirmed topic; creates the file (and its parent dir) if
    absent. Each entry carries enough context for a human to turn it into a
    ``model.yaml`` node by hand: the classifier's ``topic_hint``, the item that
    triggered it, the original feedback text, and when."""
    p = Path(path)
    yaml = _yaml()
    if p.exists():
        with p.open(encoding="utf-8") as fh:
            data = yaml.load(fh) or []
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        data = []

    data.append({"hint": hint, "url": url, "text": text, "first_seen": ts})

    with p.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
