"""SROTAS-022 — Lumi store.json adapter: role=user extraction only.

Fixture matches the real on-disk shape (confirmed against lumi/core/
repository.py::Message and a live store.json): messages(dict keyed by
session_id -> list of {role, text, ...}). No network, no real snapshot needed.
"""

import json

import pytest

from bootstrap.lumi_snapshot import read_units

FIXTURE = {
    "sessions": {
        "s1": {
            "id": "s1",
            "user_id": "owner",
            "started_at": "2026-06-05T00:00:00+00:00",
        }
    },
    "messages": {
        "s1": [
            {
                "session_id": "s1",
                "user_id": "owner",
                "role": "user",
                "text": "Я цікавлюсь квантовою фізикою.",
                "ts": "2026-06-05T00:01:00+00:00",
            },
            {
                "session_id": "s1",
                "user_id": "owner",
                "role": "assistant",
                "text": "Розкажи більше.",
                "ts": "2026-06-05T00:02:00+00:00",
                "emotion": "curious",
                "intensity": 0.6,
            },
            {
                "session_id": "s1",
                "user_id": "owner",
                "role": "user",
                "text": "Мене цікавить заплутаність частинок.",
                "ts": "2026-06-05T00:03:00+00:00",
            },
        ]
    },
    "facts": {"owner": [{"user_id": "owner", "fact": "not used here"}]},
    "summaries": {"owner": []},
}


def test_extracts_only_role_user_messages(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps(FIXTURE, ensure_ascii=False), encoding="utf-8")

    units = read_units(p)

    assert [u.text for u in units] == [
        "Я цікавлюсь квантовою фізикою.",
        "Мене цікавить заплутаність частинок.",
    ]
    assert all(u.source == "lumi" for u in units)


def test_multiple_sessions_are_all_read(tmp_path):
    fixture = {
        "messages": {
            "s1": [{"role": "user", "text": "перше"}],
            "s2": [{"role": "user", "text": "друге"}],
        }
    }
    p = tmp_path / "store.json"
    p.write_text(json.dumps(fixture), encoding="utf-8")

    units = read_units(p)
    assert {u.text for u in units} == {"перше", "друге"}


def test_empty_session_yields_nothing(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps({"messages": {"s1": []}}), encoding="utf-8")
    assert read_units(p) == []


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_units(tmp_path / "nope.json")


def test_malformed_json_raises(tmp_path):
    p = tmp_path / "store.json"
    p.write_text("not json at all", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read_units(p)


def test_missing_messages_key_raises(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(json.dumps({"sessions": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="messages"):
        read_units(p)
