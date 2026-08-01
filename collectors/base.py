"""SROTAS-019 — shared collector types and helpers.

``CollectSummary`` is the same shape across all three collectors (Guardian,
Wikipedia, GNews) — one home avoids three copies. Not a pinned contract
(ARCHITECTURE §Contracts doesn't reference it); relocating it doesn't affect
any collector's behavior.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class CollectSummary:
    """Counts from one collect run — ``fetched`` includes cross-node repeats."""

    nodes: int
    fetched: int
    new: int
    deduped: int


_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(text: str | None) -> str | None:
    """Strip HTML tags and decode entities.

    Every source's snippet field can carry raw HTML meant for browser
    rendering, not plain-text storage — confirmed live: Wikipedia's
    ``excerpt`` wraps matches in ``<span class="searchmatch">``, Guardian's
    ``trailText`` can carry ``<strong>``/``<br>``, and Google News RSS's
    ``description`` is *only* an ``<a>…</a>&nbsp;<font>…</font>`` wrapper.
    Without this, the raw tags render as literal text (Jinja autoescapes them
    — correctly not as markup, but visibly as tag soup).
    """
    if text is None:
        return None
    return html.unescape(_TAG_RE.sub("", text)).strip()
