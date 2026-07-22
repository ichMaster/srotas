"""SROTAS-008 — manual CLI collect over the model: integration, mocked HTTP.

Drives the full wiring (config → model → collect → items.sqlite) with a
mock-transport client and temp files; never a live or paid call.
"""

import sqlite3

import httpx

from collectors import guardian

MODEL = """\
- id: a
  label: "А"
  keywords: [alpha]
  weight: 0.8
- id: b
  label: "Б"
  keywords: [beta]
  weight: 0.5
- id: c
  label: "В"
  keywords: [gamma]
  weight: 0.6
"""

CONFIG = '[guardian]\napi_key = "test-key"\n'


def _response(results):
    return {"response": {"status": "ok", "results": results}}


def _result(url, title="T"):
    return {
        "webUrl": url,
        "webTitle": title,
        "webPublicationDate": "2026-07-01T00:00:00Z",
        "fields": {"trailText": "trail"},
    }


def test_run_collect_over_model_dedups_and_reports(tmp_path):
    model_file = tmp_path / "model.yaml"
    model_file.write_text(MODEL, encoding="utf-8")
    config_file = tmp_path / "config.toml"
    config_file.write_text(CONFIG, encoding="utf-8")
    db = tmp_path / "items.sqlite"

    # nodes a and b both surface the shared URL; c brings its own.
    per_node = {
        '"alpha"': [_result("https://g.com/shared"), _result("https://g.com/a1")],
        '"beta"': [_result("https://g.com/shared"), _result("https://g.com/b1")],
        '"gamma"': [_result("https://g.com/c1")],
    }

    def handler(request):
        return httpx.Response(200, json=_response(per_node[request.url.params["q"]]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    summary = guardian.run_collect(
        config_path=config_file, model_path=model_file, db_path=db, client=client
    )

    # 3 nodes, 5 results fetched, 4 distinct URLs, 1 dedup (shared across a & b).
    assert summary.nodes == 3
    assert summary.fetched == 5
    assert summary.new == 4
    assert summary.deduped == 1

    # The deduplicated Item set is on disk; derived columns stay NULL (phase 0.3).
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute("SELECT embedding, score, top_node FROM items").fetchall()
    finally:
        conn.close()
    assert len(rows) == 4
    assert all(row == (None, None, None) for row in rows)


def test_main_prints_run_summary(capsys, monkeypatch):
    """The CLI prints the new/deduped counts."""
    monkeypatch.setattr(
        guardian,
        "run_collect",
        lambda: guardian.CollectSummary(nodes=14, fetched=20, new=18, deduped=2),
    )
    guardian.main()
    out = capsys.readouterr().out
    assert "14 nodes" in out
    assert "18 new" in out
    assert "2 deduped" in out
