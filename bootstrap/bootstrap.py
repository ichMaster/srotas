"""SROTAS-027 — the bootstrap CLI orchestrator.

    python -m bootstrap.bootstrap --lumi PATH --claude-export PATH \\
        --browser-history PATH [--browser-history PATH ...] --notion PATH

Each source is **optional** — a partial run over whatever snapshots exist is
fine (ARCHITECTURE §Bootstrap); `--browser-history` may repeat (a real run
typically has one snapshot per browser profile). Runs every adapter present,
feeds the combined text units through the chunked extraction + merge
(`bootstrap/extract.py`), writes `bootstrap/candidates.yaml`, and appends a
`bootstrap` event to `events.sqlite` recording the snapshot paths and date
used — the same journal `core/init_memory.py` seeded for the initial model
(ARCHITECTURE §Bootstrap: "the snapshot path is a CLI argument; its path and
date are recorded in the bootstrap event").

**`memory/model.yaml` is never written here.** Enriching it from
`candidates.yaml` stays a manual review step — no code path does it
automatically, the same pattern as `pending_topics.yaml` -> `model.yaml` in
phase 0.5 (MISSION §Scope boundaries).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from bootstrap import browser_history, claude_export, extract, lumi_snapshot, notion
from bootstrap.units import TextUnit
from core import config, events

# A working artifact of the bootstrap process, not part of the memory package
# (ARCHITECTURE §Memory package lists exactly model.yaml/events.sqlite/
# pending_topics.yaml) — pre-review, derived from private snapshots, gitignored.
DEFAULT_CANDIDATES_PATH = Path("bootstrap/candidates.yaml")


@dataclass(frozen=True)
class BootstrapSummary:
    """What one bootstrap run did — printed by the CLI, and the bootstrap
    event's payload."""

    sources: dict = field(default_factory=dict)
    text_units: int = 0
    candidates: int = 0
    candidates_path: str = ""


def run_bootstrap(
    *,
    lumi_path: Path | None = None,
    claude_export_path: Path | None = None,
    browser_history_paths: list[Path] | None = None,
    notion_path: Path | None = None,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    events_db: Path = events.DEFAULT_EVENTS_DB,
    api_key: str = "",
    call=None,
    max_chars: int = extract.DEFAULT_MAX_CHARS,
) -> BootstrapSummary:
    """Run every adapter whose path was given, extract + merge candidates,
    write them, and journal the run. Absent sources are simply skipped."""
    sources: dict = {}
    units: list[TextUnit] = []

    if lumi_path is not None:
        found = lumi_snapshot.read_units(lumi_path)
        units.extend(found)
        sources["lumi"] = {"path": str(lumi_path), "units": len(found)}

    if claude_export_path is not None:
        found = claude_export.read_units(claude_export_path)
        units.extend(found)
        sources["claude_export"] = {
            "path": str(claude_export_path),
            "units": len(found),
        }

    for bh_path in browser_history_paths or []:
        found = browser_history.read_units(bh_path)
        units.extend(found)
        entry = sources.setdefault("browser_history", {"paths": [], "units": 0})
        entry["paths"].append(str(bh_path))
        entry["units"] += len(found)

    if notion_path is not None:
        found = notion.read_units(notion_path)
        units.extend(found)
        sources["notion"] = {"path": str(notion_path), "units": len(found)}

    chunks = extract.chunk_units(units, max_chars=max_chars)
    candidate_lists = [
        extract.extract_candidates(chunk, api_key, call=call) for chunk in chunks
    ]
    merged = extract.merge_candidates(candidate_lists)
    extract.write_candidates(merged, candidates_path)

    events.append_event(
        events_db,
        "bootstrap",
        None,
        {
            "sources": sources,
            "date": datetime.now(UTC).date().isoformat(),
            "text_units": len(units),
            "candidates": len(merged),
        },
    )

    return BootstrapSummary(
        sources=sources,
        text_units=len(units),
        candidates=len(merged),
        candidates_path=str(candidates_path),
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m bootstrap.bootstrap")
    parser.add_argument(
        "--lumi", type=Path, default=None, help="Lumi store.json snapshot"
    )
    parser.add_argument(
        "--claude-export",
        type=Path,
        default=None,
        help="Claude conversations.json export",
    )
    parser.add_argument(
        "--browser-history",
        type=Path,
        action="append",
        default=None,
        help="a browser history snapshot; repeat per profile",
    )
    parser.add_argument(
        "--notion", type=Path, default=None, help="Notion Markdown export directory"
    )
    args = parser.parse_args()

    cfg = config.load_config()
    summary = run_bootstrap(
        lumi_path=args.lumi,
        claude_export_path=args.claude_export,
        browser_history_paths=args.browser_history,
        notion_path=args.notion,
        api_key=cfg.anthropic_api_key,
    )

    if not summary.sources:
        print("No sources given — nothing to do. See --help.")
        return
    print(f"Sources used: {', '.join(summary.sources)}")
    print(f"Text units read: {summary.text_units}")
    print(f"Candidates written: {summary.candidates} -> {summary.candidates_path}")
    print("memory/model.yaml was NOT touched — review the candidates above, then")
    print("hand-move confirmed topics into memory/model.yaml yourself.")


if __name__ == "__main__":
    main()
