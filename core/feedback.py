"""SROTAS-016/017 — the feedback classifier and its model/journal effects.

A card's plain-text reaction is unclassifiable on its own — "more like this"
means nothing without knowing what "this" is — so the prompt carries the
**card's context** (item title + `top_node`) alongside the user's text
(ARCHITECTURE §Feedback). One Haiku-class call returns a structured
``{reaction, topic_hint}``; ``classify()`` validates it and raises rather than
silently defaulting on a malformed reply.

``apply_reaction()`` turns a validated classification into the model/journal
side effects: a ``like``/``dislike`` shifts the card's ``top_node`` weight
(clamped, ruamel round-trip) and a ``new_topic`` queues in
``pending_topics.yaml`` instead — never auto-creating a node. Every reaction
appends a ``feedback`` event carrying the original text and the item URL, and a
weight change appends a matching ``weight_update`` event, so any model change
is traceable (MISSION §Principles).

All Anthropic HTTP is **mocked** in tests — never a paid or live call in CI.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import anthropic

from core import events, model, pending_topics

# Models often wrap JSON in a markdown code fence even when told not to.
_FENCE_RE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.DOTALL)

MODEL = "claude-haiku-4-5-20251001"
REACTIONS = ("like", "dislike", "new_topic")
LIKE_DELTA = 0.05
DISLIKE_DELTA = -0.07

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


def _strip_code_fence(raw: str) -> str:
    """Strip a ```json ... ``` (or plain ``` ... ```) wrapper, if present."""
    stripped = raw.strip()
    m = _FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


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
        data = json.loads(_strip_code_fence(raw))
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


def apply_reaction(
    reaction: str,
    node_id: str | None,
    item_url: str,
    text: str,
    topic_hint: str | None = None,
    *,
    model_path: str | Path = model.DEFAULT_MODEL_PATH,
    events_db: str | Path = events.DEFAULT_EVENTS_DB,
    pending_topics_path: str | Path = pending_topics.DEFAULT_PENDING_TOPICS_PATH,
    like_delta: float = LIKE_DELTA,
    dislike_delta: float = DISLIKE_DELTA,
    ts: str | None = None,
) -> float | None:
    """Apply a validated :class:`Classification`'s model/journal side effects.

    ``like``/``dislike`` shift ``node_id``'s weight by the configured delta,
    clamped to ``[model.WEIGHT_MIN, model.WEIGHT_MAX]``, via a ruamel round-trip
    write; returns the new weight. ``new_topic`` never touches ``model.yaml`` —
    it queues in ``pending_topics.yaml`` and returns ``None``. Every call appends
    a ``feedback`` event carrying the original text and the item URL; a weight
    change additionally appends a ``weight_update`` event with the delta and
    before/after weights (MISSION §Principles — auditable).
    """
    if reaction not in REACTIONS:
        raise ValueError(f"unknown reaction {reaction!r}; expected one of {REACTIONS}")
    when = ts if ts is not None else datetime.now(UTC).isoformat()

    if reaction == "new_topic":
        events.append_event(
            events_db,
            "feedback",
            node_id,
            {
                "text": text,
                "url": item_url,
                "reaction": reaction,
                "topic_hint": topic_hint,
            },
            ts=when,
        )
        pending_topics.append_topic(
            pending_topics_path, topic_hint or "", item_url, text, ts=when
        )
        return None

    if node_id is None:
        raise ValueError(f"reaction {reaction!r} requires a node_id")

    events.append_event(
        events_db,
        "feedback",
        node_id,
        {"text": text, "url": item_url, "reaction": reaction},
        ts=when,
    )

    delta = like_delta if reaction == "like" else dislike_delta
    nodes = {n.id: n for n in model.load_model(model_path)}
    if node_id not in nodes:
        raise KeyError(f"no node with id {node_id!r} in {model_path}")
    old_weight = nodes[node_id].weight
    new_weight = min(model.WEIGHT_MAX, max(model.WEIGHT_MIN, old_weight + delta))
    model.set_weight(model_path, node_id, new_weight)

    events.append_event(
        events_db,
        "weight_update",
        node_id,
        {"delta": delta, "old_weight": old_weight, "new_weight": new_weight},
        ts=when,
    )
    return new_weight
