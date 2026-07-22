"""SROTAS-005 — config seam: tomllib read + a clear error on a missing key.

Uses temp files and the checked-in config.example.toml; no paid API or network.
"""

from pathlib import Path

import pytest

from core import config

REPO_ROOT = Path(__file__).resolve().parents[1]

VALID = """\
[guardian]
api_key = "test-guardian-key"
"""


def test_load_returns_guardian_key(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(VALID, encoding="utf-8")
    cfg = config.load_config(p)
    assert cfg.guardian_api_key == "test-guardian-key"


def test_missing_guardian_key_raises_clear_error(tmp_path):
    """A config without the Guardian key fails loudly (no unauthenticated call)."""
    p = tmp_path / "config.toml"
    p.write_text("[guardian]\n", encoding="utf-8")
    with pytest.raises(KeyError):
        config.load_config(p)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        config.load_config(tmp_path / "nope.toml")


def test_empty_guardian_key_rejected(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text('[guardian]\napi_key = "  "\n', encoding="utf-8")
    with pytest.raises(ValueError):
        config.load_config(p)


def test_example_config_documents_guardian_key():
    """The committed example documents the Guardian key shape."""
    text = (REPO_ROOT / "config.example.toml").read_text(encoding="utf-8")
    assert "[guardian]" in text
    assert "api_key" in text
