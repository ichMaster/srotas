"""SROTAS-022 — the shared unit every bootstrap adapter normalizes into.

Deliberately minimal — no windows, no segmentation, no citation validation
(all stage 2, ROADMAP §0.7 Out-of-scope). Not one of ARCHITECTURE's pinned
contracts (like `collectors.base.CollectSummary`); freely adjustable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextUnit:
    """One chunk of a person's own words, from one source."""

    source: str
    text: str
