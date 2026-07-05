"""SROTAS-004 — memory init writes exactly one provenance bootstrap event.

Temp memory dir; no paid API or network.
"""

from pathlib import Path

from core import events
from core.init_memory import SNAPSHOT_DATE, init_memory

REPO_ROOT = Path(__file__).resolve().parents[1]

_TWO_NODE_MODEL = """\
- id: alpha
  label: "Альфа"
  keywords: [one, two]
  weight: 0.6

- id: beta
  label: "Бета"
  keywords: [three]
  weight: 0.4
"""


def _write_model(tmp_path, text=_TWO_NODE_MODEL):
    p = tmp_path / "model.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_init_writes_one_bootstrap_event(tmp_path):
    model_path = _write_model(tmp_path)
    db = tmp_path / "events.sqlite"

    event_id = init_memory(model_path=model_path, events_db=db)
    assert event_id == 1

    boots = events.read_events(db, kind="bootstrap")
    assert len(boots) == 1
    payload = boots[0].payload
    assert payload["source"] == "lumi-facts"
    assert payload["snapshot_date"] == SNAPSHOT_DATE == "2026-07-04"
    assert payload["node_count"] == 2
    assert boots[0].node_id is None


def test_init_is_idempotent(tmp_path):
    model_path = _write_model(tmp_path)
    db = tmp_path / "events.sqlite"

    first = init_memory(model_path=model_path, events_db=db)
    second = init_memory(model_path=model_path, events_db=db)

    assert first == 1
    assert second is None  # no duplicate written
    assert len(events.read_events(db, kind="bootstrap")) == 1


def test_init_records_the_real_14_node_model_count(tmp_path):
    db = tmp_path / "events.sqlite"
    init_memory(model_path=REPO_ROOT / "memory" / "model.yaml", events_db=db)

    boots = events.read_events(db, kind="bootstrap")
    assert boots[0].payload["node_count"] == 14
