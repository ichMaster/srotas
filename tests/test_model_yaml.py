"""SROTAS-001 — data-shape checks for the checked-in memory/model.yaml.

Verifies the initial interest model is exactly 14 nodes in the flat prototype
node format (id, label, keywords, weight), with the candidates' evidence/work
metadata dropped. Pure file read — no paid API or network.
"""

from pathlib import Path

from ruamel.yaml import YAML

MODEL_PATH = Path(__file__).resolve().parents[1] / "memory" / "model.yaml"
ALLOWED_KEYS = {"id", "label", "keywords", "weight"}


def _load_nodes():
    yaml = YAML(typ="safe")
    with MODEL_PATH.open(encoding="utf-8") as fh:
        return yaml.load(fh)


def test_model_yaml_is_a_list_of_14_nodes():
    nodes = _load_nodes()
    assert isinstance(nodes, list)
    assert len(nodes) == 14


def test_every_node_has_exactly_the_flat_keys():
    for node in _load_nodes():
        assert set(node) == ALLOWED_KEYS, node.get("id")
        # the evidence/work metadata from model-candidates.yaml must be gone
        assert "evidence" not in node
        assert "work" not in node


def test_ids_are_unique():
    ids = [n["id"] for n in _load_nodes()]
    assert len(ids) == len(set(ids))


def test_weights_within_bounds():
    for node in _load_nodes():
        assert 0.05 <= node["weight"] <= 1.0, node["id"]


def test_keywords_are_nonempty_lists_of_strings():
    for node in _load_nodes():
        kw = node["keywords"]
        assert isinstance(kw, list) and kw, node["id"]
        assert all(isinstance(k, str) and k.strip() for k in kw), node["id"]
