"""SROTAS-016 — feedback classifier: card-context prompt, validated output,
malformed replies raise. The Anthropic call is injected; no paid/network call.
"""

import json

import pytest

from core import config, feedback


def _caller(reply):
    def call(prompt, api_key):
        return reply

    return call


def test_prompt_carries_card_context():
    """The classifier prompt includes the card's title and top_node, not just
    the raw text — "more like this" is unclassifiable without context."""
    seen = {}

    def call(prompt, api_key):
        seen["prompt"] = prompt
        seen["api_key"] = api_key
        return json.dumps({"reaction": "like", "topic_hint": None})

    feedback.classify(
        "more like this", "AI takes over", "ai-systems-development", "KEY", call=call
    )
    assert "AI takes over" in seen["prompt"]
    assert "ai-systems-development" in seen["prompt"]
    assert "more like this" in seen["prompt"]
    assert seen["api_key"] == "KEY"


def test_classify_like():
    result = feedback.classify(
        "love this",
        "T",
        "node-a",
        "KEY",
        call=_caller(json.dumps({"reaction": "like", "topic_hint": None})),
    )
    assert result.reaction == "like"
    assert result.topic_hint is None


def test_classify_dislike():
    result = feedback.classify(
        "not interested",
        "T",
        "node-a",
        "KEY",
        call=_caller(json.dumps({"reaction": "dislike"})),
    )
    assert result.reaction == "dislike"
    assert result.topic_hint is None


def test_classify_new_topic_carries_hint():
    reply = json.dumps(
        {"reaction": "new_topic", "topic_hint": "quantum computing, qubits"}
    )
    result = feedback.classify(
        "more about quantum stuff", "T", "node-a", "KEY", call=_caller(reply)
    )
    assert result.reaction == "new_topic"
    assert result.topic_hint == "quantum computing, qubits"


def test_new_topic_without_hint_raises():
    reply = json.dumps({"reaction": "new_topic", "topic_hint": None})
    with pytest.raises(ValueError, match="topic_hint"):
        feedback.classify("x", "T", "node-a", "KEY", call=_caller(reply))


def test_non_json_reply_raises():
    with pytest.raises(ValueError, match="non-JSON"):
        feedback.classify("x", "T", "node-a", "KEY", call=_caller("not json at all"))


def test_unknown_reaction_raises():
    reply = json.dumps({"reaction": "love-it-maybe"})
    with pytest.raises(ValueError, match="unknown reaction"):
        feedback.classify("x", "T", "node-a", "KEY", call=_caller(reply))


def test_config_reads_anthropic_key(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[guardian]\napi_key = "g"\n[anthropic]\napi_key = "a-key"\n',
        encoding="utf-8",
    )
    assert config.load_config(p).anthropic_api_key == "a-key"


def test_config_anthropic_key_defaults_empty(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[guardian]\napi_key = "g"\n', encoding="utf-8")
    assert config.load_config(p).anthropic_api_key == ""
