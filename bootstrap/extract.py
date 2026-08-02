"""SROTAS-026 — chunked LLM extraction + duplicate merge.

Batches every source's `TextUnit`s into character-bounded chunks, sends each
chunk to a Haiku-class call that proposes candidate topics, merges duplicates
across chunks/sources, and writes `candidates.yaml` for **manual review** —
the same flat-plus-metadata shape as `spec/model-candidates.yaml`
(`id`, `label`, `keywords`, `weight`, `evidence`, `work`). Deliberately
simplified — no daily windows, no segmentation, no citation validation (all
stage 2, ROADMAP §0.7 Out-of-scope).

Here `evidence` counts how many extraction chunks surfaced a candidate (a
merge-confidence signal), not the original bootstrap's fact-count meaning —
both describe "how much backs this topic," just from different source shapes.

All Anthropic HTTP is **mocked** in tests — never a live/paid call in CI.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import anthropic
from ruamel.yaml import YAML

from bootstrap.units import TextUnit

MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_CHARS = 4000
_REQUIRED_FIELDS = ("id", "label", "keywords", "weight", "work")

# Models often wrap JSON in a markdown code fence even when told not to
# (confirmed live in core/feedback.py — the same defensive parsing applies).
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)


def chunk_units(
    units: list[TextUnit], max_chars: int = DEFAULT_MAX_CHARS
) -> list[list[TextUnit]]:
    """Group text units into chunks bounded by a character budget (not
    token-exact — simple and sufficient here). Every unit lands in exactly one
    chunk; a single unit longer than the budget still gets its own chunk."""
    chunks: list[list[TextUnit]] = []
    current: list[TextUnit] = []
    current_len = 0
    for unit in units:
        if current and current_len + len(unit.text) > max_chars:
            chunks.append(current)
            current, current_len = [], 0
        current.append(unit)
        current_len += len(unit.text)
    if current:
        chunks.append(current)
    return chunks


def _prompt(units: list[TextUnit]) -> str:
    snippets = "\n".join(f"- {u.text}" for u in units)
    return (
        "Ось особисті текстові фрагменти (власні слова людини, кілька джерел). "
        "Визнач окремі теми інтересів, які в них проглядаються.\n\n"
        "Для кожної теми виведи:\n"
        '- "id": kebab-case ідентифікатор англійською (напр. "quantum-physics")\n'
        '- "label": коротка людяна назва українською\n'
        '- "keywords": 3-8 англійських ключових слів/фраз для пошуку статей\n'
        '- "weight": орієнтовна сила інтересу, число від 0.3 до 0.9\n'
        '- "work": true, якщо це швидше робоча/професійна тема (проєкт, клієнт), '
        "а не особистий інтерес; інакше false\n\n"
        "Відповідай ЛИШЕ JSON-масивом, без жодного іншого тексту:\n"
        '[{"id": "...", "label": "...", "keywords": ["..."], "weight": 0.5, '
        '"work": false}]\n\n'
        f"Фрагменти:\n{snippets}"
    )


def _strip_code_fence(raw: str) -> str:
    stripped = raw.strip()
    m = _FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


def _call_haiku(prompt: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def extract_candidates(
    units: list[TextUnit],
    api_key: str,
    *,
    call=None,
) -> list[dict]:
    """One Haiku-class call over a chunk of text units -> validated candidate
    dicts. Raises ``ValueError`` on a malformed reply (non-JSON, not an array,
    or a candidate missing a required field) rather than silently defaulting —
    the same philosophy as ``core.feedback.classify``."""
    call = call or _call_haiku
    raw = call(_prompt(units), api_key)

    try:
        data = json.loads(_strip_code_fence(raw))
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"extraction returned non-JSON output: {raw!r}") from exc
    if not isinstance(data, list):
        raise ValueError(f"extraction reply must be a JSON array, got: {raw!r}")

    candidates = []
    for entry in data:
        if not isinstance(entry, dict) or not all(
            field in entry for field in _REQUIRED_FIELDS
        ):
            raise ValueError(f"malformed candidate entry: {entry!r}")
        candidates.append(
            {
                "id": str(entry["id"]),
                "label": str(entry["label"]),
                "keywords": [str(k) for k in entry["keywords"]],
                "weight": float(entry["weight"]),
                "work": bool(entry["work"]),
            }
        )
    return candidates


def merge_candidates(candidate_lists: list[list[dict]]) -> list[dict]:
    """Merge candidates whose ``id`` or (case-insensitive) ``label`` matches
    across chunks/sources: union their keywords, average their weight
    (weighted by how many chunks already agreed), OR their ``work`` flag, and
    count how many chunks surfaced each as ``evidence``."""
    merged: dict[str, dict] = {}
    for candidates in candidate_lists:
        for c in candidates:
            match_key = next(
                (
                    k
                    for k, existing in merged.items()
                    if k == c["id"].lower()
                    or existing["label"].strip().lower() == c["label"].strip().lower()
                ),
                None,
            )
            if match_key is None:
                merged[c["id"].lower()] = {**c, "evidence": 1}
                continue
            existing = merged[match_key]
            existing["keywords"] = list(
                dict.fromkeys(existing["keywords"] + c["keywords"])
            )
            existing["weight"] = (
                existing["weight"] * existing["evidence"] + c["weight"]
            ) / (existing["evidence"] + 1)
            existing["work"] = existing["work"] or c["work"]
            existing["evidence"] += 1
    return list(merged.values())


def write_candidates(candidates: list[dict], path: str | Path) -> None:
    """Write `candidates.yaml` — the same flat-plus-metadata shape as
    `spec/model-candidates.yaml` (a top-level `candidates:` list), via ruamel
    (ARCHITECTURE §Memory package — ruamel, not pyyaml, throughout)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    yaml = YAML()
    data = {
        "candidates": [
            {
                "id": c["id"],
                "label": c["label"],
                "keywords": c["keywords"],
                "weight": round(c["weight"], 2),
                "evidence": c["evidence"],
                "work": c["work"],
            }
            for c in candidates
        ]
    }
    with p.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
