"""SROTAS-002 — the interest model reader/writer (``memory/model.yaml``).

The model is a flat list of topic nodes. The node format is a contract that must
not drift (ARCHITECTURE §Contracts): exactly ``id``, ``label``, ``keywords``,
``weight`` — no kind/tier/half_life/related, no graph, no decay.

``model.yaml`` has two writers — the human (any time) and the code (on a weight
change). To stay human-friendly, code writes with **ruamel.yaml** in round-trip
mode, touching only the ``weight`` scalar and leaving comments and formatting
intact (MISSION §Principles; pyyaml is deliberately not used).
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from pathlib import Path

from ruamel.yaml import YAML

# The node format, exactly (ARCHITECTURE §Contracts that must not drift).
ALLOWED_KEYS = frozenset({"id", "label", "keywords", "weight"})
WEIGHT_MIN = 0.05
WEIGHT_MAX = 1.0

# Default location of the interest model within the memory package.
DEFAULT_MODEL_PATH = Path("memory/model.yaml")


@dataclass(frozen=True)
class Node:
    """One interest topic. Flat — no graph, no decay (MISSION §Glossary)."""

    id: str
    label: str
    keywords: list[str]
    weight: float


# Guard against the dataclass silently growing a field the format forbids.
assert {f.name for f in fields(Node)} == ALLOWED_KEYS


def _yaml() -> YAML:
    """A round-trip YAML that preserves comments, quotes, and flow style."""
    yaml = YAML()  # round-trip mode is the default
    yaml.preserve_quotes = True
    return yaml


def load_model(path: str | Path = DEFAULT_MODEL_PATH) -> list[Node]:
    """Load ``model.yaml`` into ``Node`` objects.

    Raises ``ValueError`` if any node carries a field outside the flat format
    (fail loudly rather than silently accept a forbidden field).
    """
    yaml = _yaml()
    with Path(path).open(encoding="utf-8") as fh:
        data = yaml.load(fh)
    if data is None:
        return []

    nodes: list[Node] = []
    for raw in data:
        keys = set(raw)
        extra = keys - ALLOWED_KEYS
        missing = ALLOWED_KEYS - keys
        if extra or missing:
            raise ValueError(
                f"node {raw.get('id')!r} does not match the flat node format "
                f"{sorted(ALLOWED_KEYS)}: extra={sorted(extra)} "
                f"missing={sorted(missing)}"
            )
        nodes.append(
            Node(
                id=str(raw["id"]),
                label=str(raw["label"]),
                keywords=[str(k) for k in raw["keywords"]],
                weight=float(raw["weight"]),
            )
        )
    return nodes


def set_weight(path: str | Path, node_id: str, weight: float) -> None:
    """Write a node's ``weight`` in place via a ruamel round-trip.

    Only the ``weight`` scalar is touched; the human's comments and formatting
    survive. ``weight`` must land within ``[0.05, 1.0]`` so the file stays valid
    (callers clamp deltas before calling — see phase 0.5 feedback).
    """
    if not (WEIGHT_MIN <= weight <= WEIGHT_MAX):
        raise ValueError(f"weight {weight} out of range [{WEIGHT_MIN}, {WEIGHT_MAX}]")
    yaml = _yaml()
    p = Path(path)
    with p.open(encoding="utf-8") as fh:
        data = yaml.load(fh)

    for raw in data:
        if raw.get("id") == node_id:
            raw["weight"] = weight
            break
    else:
        raise KeyError(f"no node with id {node_id!r} in {p}")

    with p.open("w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
