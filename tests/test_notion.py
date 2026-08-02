"""SROTAS-025 — Notion Markdown export adapter: nested files, title extraction
from a # heading or the filename (Notion's trailing hex block-id stripped).
No network, no real export needed.
"""

import pytest

from bootstrap.notion import read_units


def test_reads_every_md_file_including_nested(tmp_path):
    (tmp_path / "Page One.md").write_text("# Page One\nSome content here.")
    sub = tmp_path / "Subpages"
    sub.mkdir()
    (sub / "Nested Page.md").write_text("# Nested Page\nNested content.")

    units = read_units(tmp_path)

    assert len(units) == 2
    assert all(u.source == "notion" for u in units)
    texts = {u.text for u in units}
    assert any("Some content here." in t for t in texts)
    assert any("Nested content." in t for t in texts)


def test_title_from_heading_when_present(tmp_path):
    (tmp_path / "whatever-filename.md").write_text("# Real Title\nBody text.")
    (unit,) = read_units(tmp_path)
    assert unit.text.startswith("Real Title\n")


def test_title_from_filename_strips_notion_block_id(tmp_path):
    # Notion's real export naming: "{Page Title} {32-hex-char id}.md"
    (tmp_path / "My Notes a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4.md").write_text(
        "Just body text, no heading."
    )
    (unit,) = read_units(tmp_path)
    assert unit.text.startswith("My Notes\n")


def test_empty_files_are_skipped(tmp_path):
    (tmp_path / "empty.md").write_text("   ")
    (tmp_path / "real.md").write_text("# Real\nContent.")
    units = read_units(tmp_path)
    assert len(units) == 1


def test_missing_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        read_units(tmp_path / "does-not-exist")


def test_empty_directory_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="No .md files"):
        read_units(tmp_path)
