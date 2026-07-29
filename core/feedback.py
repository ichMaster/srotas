"""SROTAS-016 — the feedback classifier seam (Haiku, ``anthropic`` SDK).

A card's plain-text reaction is unclassifiable on its own — "more like this"
means nothing without knowing what "this" is — so the prompt carries the
**card's context** (item title + `top_node`) alongside the user's text
(ARCHITECTURE §Feedback). One Haiku-class call returns a structured
``{reaction, topic_hint}``; ``classify()`` validates it and raises rather than
silently defaulting on a malformed reply. All Anthropic HTTP is **mocked** in
tests — never a paid or live call in CI.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

import anthropic

MODEL = "claude-haiku-4-5-20251001"
REACTIONS = ("like", "dislike", "new_topic")

# (prompt, api_key) -> the model's raw text reply; injected so tests never call
# the network. Defaults to _call_haiku, a thin wrapper over the anthropic SDK.
Caller = Callable[[str, str], str]


@dataclass(frozen=True)
class Classification:
    """A validated classifier result. ``topic_hint`` is set only for new_topic."""

    reaction: str
    topic_hint: str | None = None


def _prompt(text: str, title: str, top_node: str) -> str:
    return (
        "A reader is looking at this article, suggested for the interest "
        f'topic "{top_node}":\n'
        f"Title: {title}\n\n"
        f'Their reaction, in their own words:\n"{text}"\n\n'
        "Classify the reaction as exactly one of: like, dislike, new_topic.\n"
        '"new_topic" means the reaction points at an interest other than '
        f'"{top_node}" itself.\n\n'
        "Reply with ONLY a JSON object, no other text:\n"
        '{"reaction": "like|dislike|new_topic", '
        '"topic_hint": "short name + a few keywords" or null}\n'
        '"topic_hint" is required (non-null) only when reaction is "new_topic".'
    )


def _call_haiku(prompt: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=MODEL,
        max_tokens=200,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.content[0].text


def classify(
    text: str,
    title: str,
    top_node: str,
    api_key: str,
    *,
    call: Caller | None = None,
) -> Classification:
    """Classify a card's feedback text into a validated :class:`Classification`.

    Raises ``ValueError`` on a malformed reply (non-JSON, an unknown reaction, or
    a missing ``topic_hint`` on ``new_topic``) rather than guessing a default.
    """
    call = call or _call_haiku
    raw = call(_prompt(text, title, top_node), api_key)

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError(f"classifier returned non-JSON output: {raw!r}") from exc

    reaction = data.get("reaction") if isinstance(data, dict) else None
    if reaction not in REACTIONS:
        raise ValueError(f"classifier returned an unknown reaction: {reaction!r}")

    topic_hint = data.get("topic_hint")
    if reaction == "new_topic":
        if not topic_hint:
            raise ValueError("classifier reaction is new_topic but topic_hint is empty")
    else:
        topic_hint = None

    return Classification(reaction=reaction, topic_hint=topic_hint)
