"""SROTAS-005 — the configuration seam (``config.toml``).

Read-only access to ``config.toml`` via the stdlib ``tomllib``. The file is
hand-edited and has **no write path** (ARCHITECTURE §Configuration); it is
gitignored, and a committed ``config.example.toml`` documents the shape.

This phase needs only the Guardian API key. Later phases grow the file — the
Voyage and Anthropic keys, the cosine threshold, the collection interval, the
weight deltas, the topic blacklist — and each is added in its own phase, never
ahead of it (MISSION §Scope boundaries is binding, so no empty placeholders for
later stages here).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

# Default location of the (gitignored) config within the repo root.
DEFAULT_CONFIG_PATH = Path("config.toml")


@dataclass(frozen=True)
class Config:
    """A typed view over ``config.toml``; grows one field per phase as needed."""

    guardian_api_key: str


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Load and validate ``config.toml`` into a :class:`Config`.

    Fails loudly rather than let a collector fall back to an unauthenticated
    call: a missing file raises ``FileNotFoundError`` (pointing at the example),
    a missing Guardian key raises ``KeyError``, and an empty key raises
    ``ValueError``.
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(
            f"{p} not found — copy config.example.toml to config.toml and fill "
            f"in your keys"
        )
    with p.open("rb") as fh:
        data = tomllib.load(fh)

    try:
        guardian_key = data["guardian"]["api_key"]
    except (KeyError, TypeError):
        raise KeyError(
            "config.toml is missing the Guardian API key ([guardian] api_key)"
        ) from None
    if not isinstance(guardian_key, str) or not guardian_key.strip():
        raise ValueError("[guardian] api_key must be a non-empty string")

    return Config(guardian_api_key=guardian_key)
