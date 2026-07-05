"""SROTAS-004 — memory-package initialization.

Creating the memory package records where the interest model came from: on first
creation this writes a single ``bootstrap`` event whose payload traces the model
to the Lumi facts snapshot (ARCHITECTURE §Bootstrap / Initial model). This is the
one sanctioned bit of provenance wiring — no scoring, embedding, or collector
code lives here (phase Out-of-scope).

Run once to materialize the package::

    python -m core.init_memory
"""

from __future__ import annotations

from pathlib import Path

from core import events, model

# Provenance of the initial 14-node model (MISSION §Relationship to Lumi).
BOOTSTRAP_SOURCE = "lumi-facts"
SNAPSHOT_DATE = "2026-07-04"

DEFAULT_EVENTS_DB = Path("memory/events.sqlite")


def init_memory(
    model_path: str | Path = model.DEFAULT_MODEL_PATH,
    events_db: str | Path = DEFAULT_EVENTS_DB,
) -> int | None:
    """Ensure the memory package carries its provenance bootstrap event.

    Idempotent: writes exactly one ``bootstrap`` event the first time and returns
    its id; on any later call it finds the existing event and returns ``None``.
    """
    events.init_db(events_db)
    if events.read_events(events_db, kind="bootstrap"):
        return None

    nodes = model.load_model(model_path)
    payload = {
        "source": BOOTSTRAP_SOURCE,
        "snapshot_date": SNAPSHOT_DATE,
        "node_count": len(nodes),
    }
    return events.append_event(events_db, "bootstrap", None, payload)


def main() -> None:
    result = init_memory()
    if result is None:
        print("bootstrap event already present — nothing to do")
    else:
        print(f"wrote bootstrap event id={result}")


if __name__ == "__main__":
    main()
