"""SROTAS-013 — web feed: scored cards, fresh days first, score desc within a day.

FastAPI TestClient only; no paid API or network. The node label comes from the
checked-in memory/model.yaml.
"""

from fastapi.testclient import TestClient

from core import items
from web import app as webapp


def _seed(db, url, score, top_node, published_at, title):
    items.upsert(db, items.Item(url, "guardian", title, "s", published_at))
    items.set_score(db, url, score, top_node)


def _client(db, monkeypatch):
    monkeypatch.setattr(webapp, "DB_PATH", db)
    return TestClient(webapp.app)


def test_feed_renders_cards_sorted(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    _seed(db, "u1", 0.30, "ai-systems-development", "2026-07-28", "Older lower")
    _seed(db, "u2", 0.50, "ai-systems-development", "2026-07-29", "Fresh high")
    _seed(db, "u3", 0.40, "science-fiction-literature", "2026-07-29", "Fresh mid")

    resp = _client(db, monkeypatch).get("/")
    assert resp.status_code == 200
    body = resp.text
    # fresh day (07-29) section before the older one (07-28)
    assert body.index("2026-07-29") < body.index("2026-07-28")
    # within 07-29, the higher score (u2, 0.50) before the lower (u3, 0.40)
    assert body.index("Fresh high") < body.index("Fresh mid")
    # the node tag shows the top_node's Ukrainian label from model.yaml
    assert "Розробка AI-систем" in body


def test_unscored_items_are_not_shown(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    items.upsert(db, items.Item("u-nul", "guardian", "Unscored", "s", "2026-07-29"))
    _seed(db, "u-ok", 0.42, "ai-systems-development", "2026-07-29", "Scored")

    body = _client(db, monkeypatch).get("/").text
    assert "Scored" in body
    assert "Unscored" not in body  # top_node NULL → not in the feed


def test_card_has_a_feedback_field(tmp_path, monkeypatch):
    # Superseded by SROTAS-018: the field now posts to /feedback (no longer
    # inert) — see tests/test_feedback_route.py for the full wiring coverage.
    db = tmp_path / "items.sqlite"
    _seed(db, "u1", 0.42, "ai-systems-development", "2026-07-29", "T")
    body = _client(db, monkeypatch).get("/").text
    assert 'name="text"' in body


def test_empty_feed_renders(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    items.init_db(db)
    resp = _client(db, monkeypatch).get("/")
    assert resp.status_code == 200
    assert "Порожньо" in resp.text


def test_app_binds_to_localhost_only():
    assert webapp.HOST == "127.0.0.1"


# --- SROTAS-014: clickable node-tag filter ---


def test_node_filter_narrows_and_resets(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    _seed(db, "u-ai", 0.50, "ai-systems-development", "2026-07-29", "AI item")
    _seed(db, "u-sf", 0.40, "science-fiction-literature", "2026-07-29", "SciFi item")
    client = _client(db, monkeypatch)

    filtered = client.get("/?node=ai-systems-development").text
    assert "AI item" in filtered
    assert "SciFi item" not in filtered  # narrowed to one node

    full = client.get("/").text  # reset shows all
    assert "AI item" in full and "SciFi item" in full


def test_card_tag_links_to_its_node_filter(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    _seed(db, "u-ai", 0.50, "ai-systems-development", "2026-07-29", "AI item")
    body = _client(db, monkeypatch).get("/").text
    assert 'href="/?node=ai-systems-development"' in body


def test_all_reset_link_only_when_filtered(tmp_path, monkeypatch):
    db = tmp_path / "items.sqlite"
    _seed(db, "u-ai", 0.50, "ai-systems-development", "2026-07-29", "AI item")
    client = _client(db, monkeypatch)
    assert ">всі<" in client.get("/?node=ai-systems-development").text
    assert ">всі<" not in client.get("/").text
