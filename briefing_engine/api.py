"""
api.py — The web layer. Run with:  uvicorn briefing_engine.api:app --reload

This is the "User Query via API" box from the original architecture diagram:

    Browser (search form)  ->  POST /api/briefing  ->  cache?  ->  crew.kickoff()
                                                          |
                                                   (hit: serve instantly,
                                                    spend zero quota)

WHY THE CACHE IS THE WHOLE GAME HERE:
    One briefing costs ~15-20 LLM requests and ~2 minutes. The free tier allows
    ~1,000 requests/day. Without a cache, ~50 visitors kill the demo; with a
    per-fixture daily cache, the 1st visitor pays and everyone after is free
    and instant. (Bonus: search-derived stats vary run to run — caching also
    makes the day's briefing consistent for everyone.)
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .crew import DEFAULT_MODEL, FALLBACK_MODELS, build_crew
from .schemas import BriefingOutput, FixtureRequest

logger = logging.getLogger("briefing_engine.api")

app = FastAPI(title="GOLAZO — World Cup 2026 Briefing API")

_STATIC_DIR = Path(__file__).parent / "static"

# ---------------------------------------------------------------------------
# Cache + concurrency guard.
# ---------------------------------------------------------------------------
# {cache_key: API payload dict}. In-memory is fine for a single-process demo;
# swap for Redis/SQLite if this ever runs on more than one worker.
_cache: dict[str, dict] = {}

# One crew at a time. kickoff() is slow and quota-hungry; serializing requests
# protects the free tier from a burst of visitors generating simultaneously.
_generation_lock = threading.Lock()


def _cache_key(fixture: FixtureRequest) -> str:
    """One briefing per fixture per day. Order-insensitive: USA vs Germany
    and Germany vs USA share an entry."""
    teams = sorted([fixture.home_team.strip().lower(),
                    fixture.away_team.strip().lower()])
    return f"{teams[0]}|{teams[1]}|{date.today().isoformat()}"


# ---------------------------------------------------------------------------
# Request/response models — the API's own border control.
# ---------------------------------------------------------------------------
class BriefingRequest(BaseModel):
    home_team: str
    away_team: str
    venue: str = "TBD"


class BriefingResponse(BaseModel):
    briefing: BriefingOutput
    cached: bool
    generated_at: str
    model: str


def _is_transient(err: Exception) -> bool:
    """Congestion (503), quota (429), or an empty LLM response — all worth
    retrying on a DIFFERENT model, since load and quotas are per model."""
    s = str(err)
    return any(marker in s for marker in
               ("503", "UNAVAILABLE", "429", "RESOURCE_EXHAUSTED", "empty"))


def _kickoff_with_fallback(inputs: dict) -> tuple[object, str]:
    """Try the default model, then each fallback. Returns (result, model)."""
    chain = [DEFAULT_MODEL, *FALLBACK_MODELS]
    last_err: Exception | None = None
    for i, model in enumerate(chain):
        try:
            if i > 0:
                logger.warning("Falling back to %s (attempt %d/%d)",
                               model, i + 1, len(chain))
            return build_crew(model).kickoff(inputs=inputs), model
        except Exception as e:
            last_err = e
            if not _is_transient(e) or i == len(chain) - 1:
                raise
    raise last_err  # unreachable, keeps the type checker honest


# ---------------------------------------------------------------------------
# Routes.
# ---------------------------------------------------------------------------
@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "cached_briefings": len(_cache)}


@app.post("/api/briefing", response_model=BriefingResponse)
def create_briefing(req: BriefingRequest) -> BriefingResponse:
    # Reuse the same schema the CLI validates with — one contract, two doors.
    fixture = FixtureRequest(home_team=req.home_team.strip(),
                             away_team=req.away_team.strip(),
                             venue=req.venue.strip() or "TBD")
    if fixture.home_team.lower() == fixture.away_team.lower():
        raise HTTPException(status_code=422, detail="Pick two different teams.")

    key = _cache_key(fixture)
    if key in _cache:
        logger.info("Cache hit: %s", key)
        return BriefingResponse(**_cache[key], cached=True)

    # Serialize generation. The double-check inside the lock matters: two
    # visitors can race to the lock for the same fixture; the loser must find
    # the winner's cached result instead of regenerating it.
    with _generation_lock:
        if key in _cache:
            return BriefingResponse(**_cache[key], cached=True)

        logger.info("Generating briefing: %s vs %s", fixture.home_team,
                    fixture.away_team)
        try:
            result, model_used = _kickoff_with_fallback({
                "home_team": fixture.home_team,
                "away_team": fixture.away_team,
                "venue": fixture.venue,
            })
        except Exception as e:
            logger.error("Crew failed for %s on all models: %s", key, e)
            raise HTTPException(
                status_code=503,
                detail="The agents hit an upstream error (likely LLM quota or "
                       "congestion). Try again in a minute.",
            ) from e

        briefing = getattr(result, "pydantic", None)
        if not isinstance(briefing, BriefingOutput):
            raise HTTPException(status_code=502,
                                detail="The crew returned an unvalidated result.")

        payload = {
            "briefing": briefing.model_dump(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model": model_used,
        }
        _cache[key] = payload
        return BriefingResponse(**payload, cached=False)
