"""SROTAS-022 — the Lumi `store.json` snapshot adapter.

The primary source. Reads a hand-copied (or agent-copied, MISSION decision 27)
snapshot of `lumi/.lumi/store.json` and extracts **`role=user` messages
only** — the facts/summaries/thoughts layers and the vectors file are not
used here; those already seeded the initial `model.yaml` (MISSION §Relationship
to Lumi, ARCHITECTURE §Bootstrap).

Real on-disk shape (confirmed against the live store, and against
``lumi/core/repository.py::Message``): a top-level ``"messages"`` dict, keyed
by session id, each value a list of message dicts carrying (at least)
``role`` (``"user"`` | ``"assistant"``) and ``text``. Never live — this module
only ever opens a local file.
"""

from __future__ import annotations

import json
from pathlib import Path

from bootstrap.units import TextUnit


def read_units(path: str | Path) -> list[TextUnit]:
    """Parse a Lumi `store.json` snapshot into the user's own text units.

    Raises ``FileNotFoundError`` if the snapshot is missing and ``ValueError``
    if it isn't the expected shape (a JSON object with a ``"messages"`` dict)
    — fails loudly rather than silently returning nothing.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Lumi snapshot not found: {p}")
    with p.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict) or "messages" not in data:
        raise ValueError(
            f"{p} does not look like a Lumi store.json (no 'messages' key)"
        )

    units: list[TextUnit] = []
    for session_messages in data["messages"].values():
        for message in session_messages:
            if message.get("role") == "user" and message.get("text"):
                units.append(TextUnit(source="lumi", text=message["text"]))
    return units
