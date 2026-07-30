"""SROTAS-013/014/018 — the web feed (FastAPI + HTMX).

One screen: `GET /` reads the scored items from `items.sqlite` and renders them
as cards, grouped into days (day = `date(published_at)`, falling back to
`first_seen`) with **fresh days on top** and **descending score within a day**
(ARCHITECTURE §Feed). Each card shows the title link, source, date, score, the
`top_node`'s Ukrainian label (the "why suggested"), a clickable node-tag filter
(`?node=`), and a feedback field.

`POST /feedback` closes the loop (ARCHITECTURE §Feedback): the card's text is
classified (Haiku), the classified reaction shifts the card's `top_node` weight
or queues a pending topic, and — for a weight change — the feed is re-scored
(free, embeddings cached) before the updated feed re-renders.

The app binds to **127.0.0.1 only** — `/feedback` spends money (Haiku) and
mutates the model, so it must never listen on an external interface.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import FastAPI, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from core import (
    config,
    events,
    feedback,
    items,
    model,
    pending_topics,
    pipeline,
    scoring,
)

# Never an external interface (ARCHITECTURE §Feed).
HOST = "127.0.0.1"
PORT = 8000

# The memory/item-store paths the routes read and write; overridable in tests.
DB_PATH: str | Path = items.DEFAULT_ITEMS_DB
MODEL_PATH: str | Path = model.DEFAULT_MODEL_PATH
EVENTS_DB: str | Path = events.DEFAULT_EVENTS_DB
PENDING_TOPICS_PATH: str | Path = pending_topics.DEFAULT_PENDING_TOPICS_PATH

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


def _render_feed(request: Request, node: str | None) -> HTMLResponse:
    # Filtering lives in the card tags (ARCHITECTURE §Feed): ?node=<id> narrows
    # the feed to that node; "всі" / no param resets.
    active = node if node and node != "всі" else None
    feed_items = items.read_feed(DB_PATH)
    if active:
        feed_items = [it for it in feed_items if it.top_node == active]
    labels = {n.id: n.label for n in model.load_model(MODEL_PATH)}
    days = build_days(feed_items)
    # Already-reacted cards show a persisted ack instead of the form — derived
    # from the journal, so it survives a reload or a filter navigation.
    reacted = events.latest_feedback_by_url(EVENTS_DB)
    return _TEMPLATES.TemplateResponse(
        request,
        "feed.html",
        {"days": days, "labels": labels, "node": active, "reacted": reacted},
    )


@app.get("/", response_class=HTMLResponse)
def feed(request: Request, node: str | None = Query(default=None)):
    return _render_feed(request, node)


@app.post("/feedback", response_class=HTMLResponse)
def post_feedback(
    request: Request,
    url: str = Form(...),
    title: str = Form(...),
    top_node: str = Form(...),
    text: str = Form(...),
    node: str = Form(default=""),
):
    """Classify a card's reaction, apply it, re-score on a weight change, and
    reply with an inline acknowledgement swapped into the card in place
    (ARCHITECTURE §Feedback) — the reaction + weight change is visible right
    where the reader typed it, without reordering the rest of the feed."""
    cfg = config.load_config()
    classification = feedback.classify(text, title, top_node, cfg.anthropic_api_key)

    if classification.reaction == "new_topic":
        feedback.apply_reaction(
            "new_topic",
            None,
            url,
            text,
            topic_hint=classification.topic_hint,
            model_path=MODEL_PATH,
            events_db=EVENTS_DB,
            pending_topics_path=PENDING_TOPICS_PATH,
        )
        result = {"reaction": "new_topic", "old_weight": None, "new_weight": None}
    else:
        nodes = {n.id: n for n in model.load_model(MODEL_PATH)}
        old_weight = nodes[top_node].weight
        new_weight = feedback.apply_reaction(
            classification.reaction,
            top_node,
            url,
            text,
            model_path=MODEL_PATH,
            events_db=EVENTS_DB,
            pending_topics_path=PENDING_TOPICS_PATH,
            like_delta=cfg.feedback_like_delta,
            dislike_delta=cfg.feedback_dislike_delta,
        )
        # A weight just changed — re-score so the next feed load reflects it.
        # Free: item embeddings are cached (ARCHITECTURE §Scoring).
        scoring.score_items(
            DB_PATH,
            list(nodes.values()),
            threshold=cfg.cosine_threshold,
            api_key=cfg.voyage_api_key,
        )
        result = {
            "reaction": classification.reaction,
            "old_weight": old_weight,
            "new_weight": new_weight,
        }

    return _TEMPLATES.TemplateResponse(
        request, "_ack.html", {"r": result, "node": node or None}
    )


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
