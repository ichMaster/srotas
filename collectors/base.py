"""SROTAS-019 — shared collector types.

``CollectSummary`` is the same shape across all three collectors (Guardian,
Wikipedia, GNews) — one home avoids three copies. Not a pinned contract
(ARCHITECTURE §Contracts doesn't reference it); relocating it doesn't affect
any collector's behavior.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollectSummary:
    """Counts from one collect run — ``fetched`` includes cross-node repeats."""

    nodes: int
    fetched: int
    new: int
    deduped: int
