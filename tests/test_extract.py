"""SROTAS-026 — chunked extraction + duplicate merge + candidates.yaml write.

The Anthropic call is injected; no paid/network call. Malformed-reply cases
mirror core/feedback.py's classify() philosophy — fail loudly, never default.
"""

import json

import pytest
from ruamel.yaml import YAML

from bootstrap import extract
from bootstrap.units import TextUnit


def _caller(reply):
    def call(prompt, api_key):
        return reply

    return call


def test_chunk_units_respects_character_budget():
    units = [TextUnit("lumi", "x" * 30) for _ in range(5)]
    chunks = extract.chunk_units(units, max_chars=100)
    assert sum(len(c) for c in chunks) == 5  # every unit lands somewhere
    for chunk in chunks:
        assert sum(len(u.text) for u in chunk) <= 100


def test_chunk_units_oversized_single_unit_gets_its_own_chunk():
    units = [TextUnit("lumi", "x" * 500)]
    chunks = extract.chunk_units(units, max_chars=100)
    assert len(chunks) == 1
    assert len(chunks[0]) == 1


def test_extract_candidates_parses_valid_reply():
    units = [TextUnit("lumi", "цікавлюсь квантовою фізикою")]
    reply = json.dumps(
        [
            {
                "id": "quantum-physics",
                "label": "Квантова фізика",
                "keywords": ["quantum physics", "entanglement"],
                "weight": 0.6,
                "work": False,
            }
        ]
    )
    candidates = extract.extract_candidates(units, "KEY", call=_caller(reply))
    assert candidates == [
        {
            "id": "quantum-physics",
            "label": "Квантова фізика",
            "keywords": ["quantum physics", "entanglement"],
            "weight": 0.6,
            "work": False,
        }
    ]


def test_extract_candidates_strips_markdown_code_fence():
    body = json.dumps(
        [{"id": "a", "label": "A", "keywords": ["x"], "weight": 0.5, "work": False}]
    )
    reply = f"```json\n{body}\n```"
    candidates = extract.extract_candidates(
        [TextUnit("lumi", "x")], "KEY", call=_caller(reply)
    )
    assert candidates[0]["id"] == "a"


def test_extract_candidates_non_json_raises():
    with pytest.raises(ValueError, match="non-JSON"):
        extract.extract_candidates(
            [TextUnit("lumi", "x")], "KEY", call=_caller("not json")
        )


def test_extract_candidates_non_array_raises():
    with pytest.raises(ValueError, match="JSON array"):
        extract.extract_candidates(
            [TextUnit("lumi", "x")], "KEY", call=_caller(json.dumps({"not": "array"}))
        )


def test_extract_candidates_missing_field_raises():
    reply = json.dumps([{"id": "a", "label": "A"}])  # missing keywords/weight/work
    with pytest.raises(ValueError, match="malformed candidate"):
        extract.extract_candidates([TextUnit("lumi", "x")], "KEY", call=_caller(reply))


def test_merge_candidates_by_id_unions_keywords_and_averages_weight():
    lists = [
        [
            {
                "id": "quantum-physics",
                "label": "Квантова фізика",
                "keywords": ["quantum physics"],
                "weight": 0.6,
                "work": False,
            }
        ],
        [
            {
                "id": "quantum-physics",
                "label": "Квантова фізика",
                "keywords": ["entanglement"],
                "weight": 0.8,
                "work": False,
            }
        ],
    ]
    (merged,) = extract.merge_candidates(lists)
    assert merged["keywords"] == ["quantum physics", "entanglement"]
    assert abs(merged["weight"] - 0.7) < 1e-9  # average of 0.6 and 0.8
    assert merged["evidence"] == 2


def test_merge_candidates_by_label_when_id_differs():
    lists = [
        [
            {
                "id": "quantum",
                "label": "Квантова фізика",
                "keywords": ["a"],
                "weight": 0.5,
                "work": False,
            }
        ],
        [
            {
                "id": "quantum-physics",
                "label": "Квантова фізика",
                "keywords": ["b"],
                "weight": 0.5,
                "work": False,
            }
        ],
    ]
    merged = extract.merge_candidates(lists)
    assert len(merged) == 1  # matched by label despite differing ids


def test_merge_candidates_work_flag_is_true_if_any_chunk_flags_it():
    lists = [
        [{"id": "a", "label": "A", "keywords": [], "weight": 0.5, "work": False}],
        [{"id": "a", "label": "A", "keywords": [], "weight": 0.5, "work": True}],
    ]
    (merged,) = extract.merge_candidates(lists)
    assert merged["work"] is True


def test_merge_candidates_distinct_topics_stay_separate():
    lists = [
        [{"id": "a", "label": "A", "keywords": [], "weight": 0.5, "work": False}],
        [{"id": "b", "label": "B", "keywords": [], "weight": 0.5, "work": False}],
    ]
    merged = extract.merge_candidates(lists)
    assert {c["id"] for c in merged} == {"a", "b"}


def test_write_candidates_matches_model_candidates_shape(tmp_path):
    candidates = [
        {
            "id": "quantum-physics",
            "label": "Квантова фізика",
            "keywords": ["quantum physics", "entanglement"],
            "weight": 0.65,
            "evidence": 2,
            "work": False,
        }
    ]
    path = tmp_path / "candidates.yaml"
    extract.write_candidates(candidates, path)

    yaml = YAML()
    with path.open(encoding="utf-8") as fh:
        loaded = yaml.load(fh)

    assert "candidates" in loaded
    entry = loaded["candidates"][0]
    assert entry["id"] == "quantum-physics"
    assert entry["label"] == "Квантова фізика"
    assert list(entry["keywords"]) == ["quantum physics", "entanglement"]
    assert entry["weight"] == 0.65
    assert entry["evidence"] == 2
    assert entry["work"] is False
