"""SROTAS-015 — the in-process scheduler: the collect→embed→score job is
registered on the configured interval, and running it drives the pass with
collection mocked. No paid API or network.
"""

from core import config
from web import app as webapp


def test_job_registered_with_configured_interval():
    scheduler = webapp.build_scheduler(4)
    scheduler.start(paused=True)  # started (so get_job works) but nothing fires
    try:
        job = scheduler.get_job("collect-embed-score")
        assert job is not None
        assert job.func is webapp.run_collection_pass
        assert job.trigger.interval.total_seconds() == 4 * 3600
    finally:
        scheduler.shutdown(wait=False)


def test_default_interval_is_four_hours(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[guardian]\napi_key = "g"\n', encoding="utf-8")
    assert config.load_config(p).collection_interval_hours == 4.0


def test_configured_interval_is_read(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[guardian]\napi_key = "g"\n[schedule]\ninterval_hours = 6\n',
        encoding="utf-8",
    )
    assert config.load_config(p).collection_interval_hours == 6.0


def test_collection_pass_runs_the_pipeline(monkeypatch, tmp_path):
    """The job runs collect→embed→score; collection is mocked (no network)."""
    calls = {}

    def fake_run_pass(**kwargs):
        calls["db_path"] = kwargs.get("db_path")
        return None

    monkeypatch.setattr(webapp.pipeline, "run_pass", fake_run_pass)
    monkeypatch.setattr(webapp, "DB_PATH", tmp_path / "items.sqlite")

    webapp.run_collection_pass()
    assert calls["db_path"] == tmp_path / "items.sqlite"
