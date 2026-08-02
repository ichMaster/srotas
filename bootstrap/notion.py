"""SROTAS-025 — the Notion Markdown export adapter.

Reads a directory tree of `.md` files — the shape of both a manual Notion
Markdown export (Settings → Export) and an agent-fetched-via-MCP export
(MISSION decision 27; either way this adapter only ever reads local files,
never the API/MCP tool itself) — and extracts each page's text as one text
unit (ARCHITECTURE §Bootstrap).

Notion's own export names each file `{Page Title} {32-hex-char block id}.md`;
the trailing id is stripped when a page has no `# ` heading of its own to use
as the title instead.
"""

from __future__ import annotations

import re
from pathlib import Path

from bootstrap.units import TextUnit

_TRAILING_ID_RE = re.compile(r"\s+[0-9a-f]{32}$", re.IGNORECASE)


def _title_from_filename(path: Path) -> str:
    return _TRAILING_ID_RE.sub("", path.stem)


def read_units(path: str | Path) -> list[TextUnit]:
    """Parse a Notion Markdown export directory into per-page text units.

    Raises ``FileNotFoundError`` if the directory is missing/empty of `.md`
    files — fails loudly rather than silently returning nothing.
    """
    root = Path(path)
    if not root.is_dir():
        raise FileNotFoundError(f"Notion export directory not found: {root}")

    md_files = sorted(root.rglob("*.md"))
    if not md_files:
        raise FileNotFoundError(f"No .md files found under {root}")

    units: list[TextUnit] = []
    for md_file in md_files:
        body = md_file.read_text(encoding="utf-8").strip()
        if not body:
            continue
        first_line = body.splitlines()[0]
        title = (
            first_line[2:].strip()
            if first_line.startswith("# ")
            else _title_from_filename(md_file)
        )
        units.append(TextUnit(source="notion", text=f"{title}\n{body}"))
    return units
