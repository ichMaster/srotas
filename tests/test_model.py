"""SROTAS-002 — model reader/writer: flat-format contract + ruamel round-trip.

Uses temp files and the checked-in memory/model.yaml; no paid API or network.
"""

from dataclasses import fields
from pathlib import Path

import pytest

from core import model

REPO_ROOT = Path(__file__).resolve().parents[1]

FIXTURE_WITH_COMMENT = """\
# keep me — a human comment
- id: alpha
  label: "Альфа"
  keywords: [one, two, three]
  weight: 0.60

- id: beta
  label: "Бета"
  keywords: [four, five]
  weight: 0.40
"""


def test_load_checked_in_model_returns_14_nodes():
    nodes = model.load_model(REPO_ROOT / "memory" / "model.yaml")
    assert len(nodes) == 14
    assert all(isinstance(n, model.Node) for n in nodes)
    ids = [n.id for n in nodes]
    assert len(ids) == len(set(ids))


def test_node_has_exactly_the_flat_fields():
    """Contract: Node exposes exactly id, label, keywords, weight."""
    assert {f.name for f in fields(model.Node)} == {
        "id",
        "label",
        "keywords",
        "weight",
    }


def test_extra_node_field_is_rejected(tmp_path):
    """Contract: a node with a forbidden field (e.g. tier) fails loudly."""
    bad = tmp_path / "model.yaml"
    bad.write_text(
        '- id: x\n  label: "X"\n  keywords: [a]\n  weight: 0.5\n  tier: 1\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="flat node format"):
        model.load_model(bad)


def test_missing_node_field_is_rejected(tmp_path):
    bad = tmp_path / "model.yaml"
    bad.write_text('- id: x\n  label: "X"\n  weight: 0.5\n', encoding="utf-8")
    with pytest.raises(ValueError, match="flat node format"):
        model.load_model(bad)


def test_set_weight_round_trip_preserves_comment_and_other_nodes(tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text(FIXTURE_WITH_COMMENT, encoding="utf-8")

    model.set_weight(path, "alpha", 0.75)

    # The weight is persisted...
    reloaded = {n.id: n.weight for n in model.load_model(path)}
    assert reloaded["alpha"] == 0.75
    assert reloaded["beta"] == 0.40  # untouched

    # ...and the human's comment + the untouched node survive byte-for-byte.
    text = path.read_text(encoding="utf-8")
    assert "# keep me — a human comment" in text
    assert 'label: "Альфа"' in text
    assert "keywords: [one, two, three]" in text  # flow style preserved
    assert "weight: 0.40" in text  # beta's scalar untouched


def test_set_weight_rejects_out_of_range(tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text(FIXTURE_WITH_COMMENT, encoding="utf-8")
    with pytest.raises(ValueError):
        model.set_weight(path, "alpha", 1.5)
    with pytest.raises(ValueError):
        model.set_weight(path, "alpha", 0.0)


def test_set_weight_unknown_node_raises(tmp_path):
    path = tmp_path / "model.yaml"
    path.write_text(FIXTURE_WITH_COMMENT, encoding="utf-8")
    with pytest.raises(KeyError):
        model.set_weight(path, "does-not-exist", 0.5)
