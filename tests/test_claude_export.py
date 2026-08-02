"""SROTAS-023 — Claude export adapter: human turns only, both text shapes.

Fixture matches the real claude.ai data-export shape (a JSON array of
conversations, each with chat_messages carrying sender + text/content). No
network, no real export needed.
"""

import json

import pytest

from bootstrap.claude_export import read_units

FIXTURE = [
    {
        "uuid": "conv-1",
        "name": "Quantum physics chat",
        "chat_messages": [
            {
                "uuid": "m1",
                "sender": "human",
                "text": "Розкажи про квантову заплутаність.",
            },
            {"uuid": "m2", "sender": "assistant", "text": "Звісно, ось пояснення."},
            {
                "uuid": "m3",
                "sender": "human",
                "text": "",
                "content": [{"type": "text", "text": "А що таке декогеренція?"}],
            },
        ],
    },
    {
        "uuid": "conv-2",
        "name": "Second conversation",
        "chat_messages": [
            {"uuid": "m4", "sender": "human", "text": "Інша розмова."},
        ],
    },
]


def test_extracts_only_human_messages_across_conversations(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")

    units = read_units(p)

    assert [u.text for u in units] == [
        "Розкажи про квантову заплутаність.",
        "А що таке декогеренція?",
        "Інша розмова.",
    ]
    assert all(u.source == "claude_export" for u in units)


def test_falls_back_to_content_blocks_when_text_is_empty(tmp_path):
    fixture = [
        {
            "chat_messages": [
                {
                    "sender": "human",
                    "text": "",
                    "content": [
                        {"type": "text", "text": "перший блок"},
                        {"type": "text", "text": "другий блок"},
                    ],
                }
            ]
        }
    ]
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")

    (unit,) = read_units(p)
    assert unit.text == "перший блок\nдругий блок"


def test_empty_export_yields_nothing(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text("[]", encoding="utf-8")
    assert read_units(p) == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_units(tmp_path / "nope.json")


def test_malformed_json_raises(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_units(p)


def test_non_array_top_level_raises(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(json.dumps({"not": "an array"}), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON array"):
        read_units(p)
