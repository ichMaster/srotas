"""SROTAS-023 — the Claude data-export adapter.

Reads the archive from claude.ai Settings → Privacy → Export data
(`conversations.json`) and extracts the human's own turns as text units
(ARCHITECTURE §Bootstrap). The export has no API — a one-off download the
owner triggers themselves (an authenticated claude.ai account action, not a
local file the agent can produce; MISSION decision 27).

Real export shape: a top-level JSON array of conversations, each with a
``chat_messages`` array of ``{sender: "human" | "assistant", text, content}``.
Some messages carry their text only in ``content`` blocks
(``[{"type": "text", "text": "..."}]``) rather than the top-level ``text``
field — both are handled.
"""

from __future__ import annotations

import json
from pathlib import Path

from bootstrap.units import TextUnit


def _message_text(message: dict) -> str:
    """A chat message's text — the top-level field, or joined text content
    blocks when that field is empty (a real export quirk)."""
    text = message.get("text") or ""
    if text:
        return text
    blocks = message.get("content") or []
    parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
    return "\n".join(p for p in parts if p)


def read_units(path: str | Path) -> list[TextUnit]:
    """Parse a Claude `conversations.json` export into the human's own text
    units.

    Raises ``FileNotFoundError`` if the export is missing and ``ValueError``
    if it isn't the expected shape (a JSON array of conversations) — fails
    loudly rather than silently returning nothing.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Claude export not found: {p}")
    with p.open(encoding="utf-8") as fh:
        try:
            data = json.load(fh)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{p} is not valid JSON: {exc}") from exc

    if not isinstance(data, list):
        raise ValueError(
            f"{p} does not look like a Claude export (expected a JSON array)"
        )

    units: list[TextUnit] = []
    for conversation in data:
        for message in conversation.get("chat_messages", []):
            if message.get("sender") != "human":
                continue
            text = _message_text(message)
            if text:
                units.append(TextUnit(source="claude_export", text=text))
    return units
