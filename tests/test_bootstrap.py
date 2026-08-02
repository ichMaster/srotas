"""SROTAS-027 — bootstrap CLI orchestrator: partial runs, full runs, the
bootstrap event, and the "never writes model.yaml" contract. All Anthropic
HTTP is mocked; no real snapshots needed.
"""

import json
import sqlite3

from ruamel.yaml import YAML

from bootstrap.bootstrap import run_bootstrap
from core import events


def _fake_call(prompt, api_key):
    return json.dumps(
        [
            {
                "id": "quantum-physics",
                "label": "Квантова фізика",
                "keywords": ["quantum physics"],
                "weight": 0.6,
                "work": False,
            }
        ]
    )


def _lumi_snapshot(tmp_path):
    p = tmp_path / "store.json"
    p.write_text(
        json.dumps(
            {"messages": {"s1": [{"role": "user", "text": "квантова фізика цікавить"}]}}
        ),
        encoding="utf-8",
    )
    return p


def _claude_export(tmp_path):
    p = tmp_path / "conversations.json"
    p.write_text(
        json.dumps(
            [
                {
                    "chat_messages": [
                        {"sender": "human", "text": "розкажи про квантову фізику"}
                    ]
                }
            ]
        ),
        encoding="utf-8",
    )
    return p


def _browser_history(tmp_path):
    p = tmp_path / "History"
    conn = sqlite3.connect(p)
    conn.execute("CREATE TABLE urls(url LONGVARCHAR, title LONGVARCHAR)")
    conn.execute(
        "INSERT INTO urls VALUES (?, ?)",
        ("https://en.wikipedia.org/wiki/Quantum_mechanics", "Quantum mechanics"),
    )
    conn.commit()
    conn.close()
    return p


def _notion_export(tmp_path):
    d = tmp_path / "notion"
    d.mkdir()
    (d / "Notes.md").write_text("# Notes\nQuantum computing thoughts.")
    return d


def test_partial_run_with_only_lumi_works(tmp_path):
    candidates_path = tmp_path / "candidates.yaml"
    events_db = tmp_path / "events.sqlite"

    summary = run_bootstrap(
        lumi_path=_lumi_snapshot(tmp_path),
        candidates_path=candidates_path,
        events_db=events_db,
        call=_fake_call,
    )

    expected_path = str(_lumi_snapshot(tmp_path))
    assert summary.sources == {"lumi": {"path": expected_path, "units": 1}}
    assert summary.text_units == 1
    assert candidates_path.exists()


def test_full_run_over_all_four_sources(tmp_path):
    candidates_path = tmp_path / "candidates.yaml"
    events_db = tmp_path / "events.sqlite"

    summary = run_bootstrap(
        lumi_path=_lumi_snapshot(tmp_path),
        claude_export_path=_claude_export(tmp_path),
        browser_history_paths=[_browser_history(tmp_path)],
        notion_path=_notion_export(tmp_path),
        candidates_path=candidates_path,
        events_db=events_db,
        call=_fake_call,
    )

    assert set(summary.sources) == {
        "lumi",
        "claude_export",
        "browser_history",
        "notion",
    }
    assert summary.text_units == 4  # one unit from each source
    assert summary.candidates == 1  # the mocked reply always proposes the same topic

    yaml = YAML()
    with candidates_path.open(encoding="utf-8") as fh:
        data = yaml.load(fh)
    assert data["candidates"][0]["id"] == "quantum-physics"
    # all 4 tiny fixture units fit in a single chunk under the default
    # character budget, so extract_candidates is called once -> evidence 1.
    assert data["candidates"][0]["evidence"] == 1


def test_repeated_browser_history_flag_reads_every_profile(tmp_path):
    p1 = tmp_path / "p1"
    p1.mkdir()
    p2 = tmp_path / "p2"
    p2.mkdir()
    h1 = _browser_history(p1)
    h2 = _browser_history(p2)

    summary = run_bootstrap(
        browser_history_paths=[h1, h2],
        candidates_path=tmp_path / "candidates.yaml",
        events_db=tmp_path / "events.sqlite",
        call=_fake_call,
    )
    assert summary.sources["browser_history"]["units"] == 2
    assert len(summary.sources["browser_history"]["paths"]) == 2


def test_bootstrap_event_is_appended_with_snapshot_paths(tmp_path):
    events_db = tmp_path / "events.sqlite"
    lumi_path = _lumi_snapshot(tmp_path)

    run_bootstrap(
        lumi_path=lumi_path,
        candidates_path=tmp_path / "candidates.yaml",
        events_db=events_db,
        call=_fake_call,
    )

    (bootstrap_event,) = events.read_events(events_db, kind="bootstrap")
    assert bootstrap_event.payload["sources"]["lumi"]["path"] == str(lumi_path)
    assert "date" in bootstrap_event.payload
    assert bootstrap_event.payload["text_units"] == 1


def test_model_yaml_is_never_written(tmp_path, monkeypatch):
    """No source ever touches memory/model.yaml — enrichment is a manual
    review step (MISSION §Scope boundaries)."""
    monkeypatch.chdir(tmp_path)  # so a bug writing "memory/model.yaml" would
    # land right where we can see it, not the real repo's file
    run_bootstrap(
        lumi_path=_lumi_snapshot(tmp_path),
        candidates_path=tmp_path / "candidates.yaml",
        events_db=tmp_path / "events.sqlite",
        call=_fake_call,
    )
    assert not (tmp_path / "memory").exists()


def test_no_sources_yields_an_empty_but_valid_run(tmp_path):
    summary = run_bootstrap(
        candidates_path=tmp_path / "candidates.yaml",
        events_db=tmp_path / "events.sqlite",
        call=_fake_call,
    )
    assert summary.sources == {}
    assert summary.text_units == 0
    assert summary.candidates == 0
