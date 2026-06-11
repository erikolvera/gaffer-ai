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

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

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
# Two tiers. The dict is the fast tier; Redis (REDIS_URL, e.g. a free Upstash
# instance) is the durable tier. Render's free tier spins the process down
# after ~15 idle minutes — without Redis, every wake-up starts with an empty
# cache and repeat visitors re-spend ~15-20 LLM calls per fixture.
_cache: dict[str, dict] = {}
_CACHE_TTL_SECONDS = 48 * 3600  # fixtures are dated; let old entries lapse

_redis = None
if os.getenv("REDIS_URL") and not os.getenv("CACHE_REDIS_URL"):
    # Deliberately NOT honored: libraries in the agent stack auto-detect the
    # well-known REDIS_URL name, build their own (mis-TLS-configured) clients,
    # and crash mid-crew. Use CACHE_REDIS_URL for the briefing cache.
    logger.warning("Ignoring REDIS_URL (third-party libs hijack that name); "
                   "set CACHE_REDIS_URL instead")
if os.getenv("CACHE_REDIS_URL"):
    try:
        import certifi
        import redis as _redis_lib

        _url = os.environ["CACHE_REDIS_URL"].strip()
        _kwargs: dict = {"socket_timeout": 3, "decode_responses": True}
        if _url.startswith("rediss://"):
            # Pin the CA bundle explicitly: some Pythons (notably python.org
            # macOS builds) can't see the system cert store, which fails TLS
            # verification against Upstash with CERTIFICATE_VERIFY_FAILED.
            _kwargs["ssl_ca_certs"] = certifi.where()
        _redis = _redis_lib.Redis.from_url(_url, **_kwargs)
        _redis.ping()
        logger.info("Durable cache: Redis connected")
    except Exception as e:
        # Never let the cache backend take the demo down — degrade to memory.
        logger.warning("Durable cache unavailable (%s); running memory-only", e)
        _redis = None
else:
    logger.info("CACHE_REDIS_URL not set; cache is memory-only "
                "(won't survive process restarts)")


def _store_get(key: str) -> dict | None:
    if key in _cache:
        return _cache[key]
    if _redis is not None:
        try:
            raw = _redis.get(key)
            if raw:
                payload = json.loads(raw)
                _cache[key] = payload  # re-warm the fast tier
                return payload
        except Exception as e:
            logger.warning("Redis read failed (%s); falling back to memory", e)
    return None


def _store_set(key: str, payload: dict) -> None:
    _cache[key] = payload
    if _redis is not None:
        try:
            _redis.set(key, json.dumps(payload), ex=_CACHE_TTL_SECONDS)
        except Exception as e:
            logger.warning("Redis write failed (%s); entry is memory-only", e)


# One crew at a time. kickoff() is slow and quota-hungry; serializing requests
# protects the free tier from a burst of visitors generating simultaneously.
_generation_lock = threading.Lock()


def _cache_key(fixture: FixtureRequest) -> str:
    """One briefing per fixture per day. Order-insensitive: USA vs Germany
    and Germany vs USA share an entry.

    The "day" is Pacific time on purpose: Gemini's free-tier quotas reset at
    midnight PT, and host-country match evenings cross the UTC date line —
    a UTC key would expire the cache at 5pm PT, right at peak traffic."""
    teams = sorted([fixture.home_team.strip().lower(),
                    fixture.away_team.strip().lower()])
    day = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    return f"{teams[0]}|{teams[1]}|{day}"


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
    return {"status": "ok", "cached_briefings": len(_cache),
            "durable_cache": _redis is not None}


@app.post("/api/briefing", response_model=BriefingResponse)
def create_briefing(req: BriefingRequest) -> BriefingResponse:
    # Reuse the same schema the CLI validates with — one contract, two doors.
    fixture = FixtureRequest(home_team=req.home_team.strip(),
                             away_team=req.away_team.strip(),
                             venue=req.venue.strip() or "TBD")
    if fixture.home_team.lower() == fixture.away_team.lower():
        raise HTTPException(status_code=422, detail="Pick two different teams.")

    key = _cache_key(fixture)
    if (hit := _store_get(key)) is not None:
        logger.info("Cache hit: %s", key)
        return BriefingResponse(**hit, cached=True)

    # Serialize generation. The double-check inside the lock matters: two
    # visitors can race to the lock for the same fixture; the loser must find
    # the winner's cached result instead of regenerating it.
    with _generation_lock:
        if (hit := _store_get(key)) is not None:
            return BriefingResponse(**hit, cached=True)

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
        _store_set(key, payload)
        return BriefingResponse(**payload, cached=False)
