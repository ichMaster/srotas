"""SROTAS-013 — the web feed (FastAPI + HTMX).

One screen: `GET /` reads the scored items from `items.sqlite` and renders them
as cards, grouped into days (day = `date(published_at)`, falling back to
`first_seen`) with **fresh days on top** and **descending score within a day**
(ARCHITECTURE §Feed). Each card shows the title link, source, date, score, the
`top_node`'s Ukrainian label (the "why suggested"), and a feedback field that
renders but **posts nowhere** (the handler is phase 0.5).

The app binds to **127.0.0.1 only** — it will expose a money-spending,
model-mutating POST at 0.5 and must never listen on an external interface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core import config, items, model, pipeline

# Never an external interface (ARCHITECTURE §Feed).
HOST = "127.0.0.1"
PORT = 8000

# The item store the feed reads; overridable in tests.
DB_PATH: str | Path = items.DEFAULT_ITEMS_DB

_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# The scheduler job id; also its handle so tests can inspect it.
_JOB_ID = "collect-embed-score"


def run_collection_pass() -> None:
    """The scheduled pass: **collect → embed → score** (translation is 0.8, not
    here). Runs in a scheduler worker thread so it never blocks the web loop."""
    pipeline.run_pass(db_path=DB_PATH)


def build_scheduler(interval_hours: float) -> BackgroundScheduler:
    """A scheduler carrying the collect→embed→score job on the given interval."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_collection_pass, "interval", hours=interval_hours, id=_JOB_ID
    )
    return scheduler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the in-process scheduler on startup; stop it on shutdown. A missing
    config.toml degrades gracefully — the feed still serves, just without the
    scheduler."""
    scheduler = None
    try:
        cfg = config.load_config()
        scheduler = build_scheduler(cfg.collection_interval_hours)
        scheduler.start()
    except FileNotFoundError:
        pass
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)


app = FastAPI(title="Srotas", lifespan=lifespan)


def _feed_day(item: items.ScoredItem) -> str:
    """The feed day for an item: published_at date, falling back to first_seen."""
    return (item.published_at or item.first_seen)[:10]


def build_days(
    feed_items: list[items.ScoredItem],
) -> list[tuple[str, list[items.ScoredItem]]]:
    """Group scored items into ``(day, cards)`` — fresh days first, score desc."""
    by_day: dict[str, list[items.ScoredItem]] = {}
    for item in feed_items:
        by_day.setdefault(_feed_day(item), []).append(item)
    days = []
    for day in sorted(by_day, reverse=True):
        cards = sorted(by_day[day], key=lambda it: it.score, reverse=True)
        days.append((day, cards))
    return days


@app.get("/", response_class=HTMLResponse)
def feed(request: Request, node: str | None = Query(default=None)):
    # Filtering lives in the card tags (ARCHITECTURE §Feed): ?node=<id> narrows
    # the feed to that node; "всі" / no param resets.
    active = node if node and node != "всі" else None
    feed_items = items.read_feed(DB_PATH)
    if active:
        feed_items = [it for it in feed_items if it.top_node == active]
    labels = {n.id: n.label for n in model.load_model()}
    days = build_days(feed_items)
    return _TEMPLATES.TemplateResponse(
        request, "feed.html", {"days": days, "labels": labels, "node": active}
    )


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
