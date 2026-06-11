# ⚽ GOLAZO — the World Cup 2026 briefing engine

Type any two national teams. Three AI agents scout the live web, break the
matchup down, and write you a fan-first matchday briefing — with real injury
news from this week, validated end-to-end by typed data contracts.
(Repo keeps its original `gaffer-ai` slug; the product is GOLAZO.)

> **Live demo:** **[golazo-fwpu.onrender.com](https://golazo-fwpu.onrender.com/)**
> (free hosting — first visit after an idle spell takes ~1 min to wake, then a
> fresh briefing takes a minute or two; cached fixtures are instant)
> **Example:** "Mexico vs South Africa" → a preview leading with Mexico's actual
> June 2026 injury crisis.

---

## How it works

```
        Browser search ──▶ POST /api/briefing ──▶ daily cache? ──▶ instant hit
                                   │ miss
                                   ▼
        ┌──────────────────────────────────────────────┐
        │       crew.py — sequential agent relay       │
        └──────────────────────────────────────────────┘
             │                  │                  │
             ▼                  ▼                  ▼
        ┌─────────┐  ctx  ┌──────────┐  ctx  ┌────────────┐
        │  SCOUT  │ ────▶ │ ANALYST  │ ────▶ │ JOURNALIST │
        │ fetches │       │ reads xG,│       │ writes the │
        │ live    │       │ shapes,  │       │ fan-first  │
        │ stats   │       │ matchups │       │ preview    │
        └─────────┘       └──────────┘       └────────────┘
             │                                     │
             ▼                                     ▼
        grounded Google                   BriefingOutput schema
        Search (Gemini)                   (hard validation, not
        → TeamMatchData                    "looks right" prompting)
```

Every hop is guarded by a Pydantic contract (`schemas.py`): the user's request
(`FixtureRequest`), the tool's payload (`TeamMatchData`), and the final answer
(`BriefingOutput`). The system's acceptance test is the **critical-alert
journey**: an injury flagged by the Scout must arrive in the final response as
a typed `escalated_alerts` object — surviving three LLM handoffs without
decaying into vibes.

## The stack

- **CrewAI** — agent orchestration (sequential process, context passing)
- **Gemini** — agent reasoning + grounded Google Search for live team news;
  3.5 Flash by default with **fallback chains** to older models when quotas
  or congestion bite
- **Pydantic v2** — data contracts at every boundary
- **FastAPI + vanilla JS** — one endpoint, one page; the UI animates the agent
  relay while the crew works
- **Redis (Upstash) · Render · GitHub Actions** — durable cache, hosting, and
  the scheduled morning warm-up (details below)

## Engineering notes (the parts that fought back)

- **Free-tier quotas are per model, and the docs lie.** Research said 250
  requests/day for `gemini-2.5-flash`; the API's 429 said `limit: 20`. The fix
  grew in layers, each from a real outage: **fallback chains** at the crew
  level (`GEMINI_MODEL` + `GEMINI_FALLBACK_MODELS`) *and* inside the grounded
  search tool (grounding has its own per-model quota), plus a **double sweep
  with a 60s backoff** — during peak load every model can briefly 503 in the
  same window, and a single chain walk is faster than the spike it's dodging.
- **Cheaper models fail quietly.** On `flash-lite`, the crew ran fine — and
  silently dropped the critical alert from the structured output. The
  alert-journey test caught it. Model choice is a correctness decision, not
  just a cost one.
- **Grounding + strict JSON don't mix in one call.** Live data is fetched in
  two steps: a grounded call researches in prose, a second call structures it
  against the schema. Both paths (live and mock fallback) pass identical
  validation — web data earns no extra trust.
- **One briefing ≈ 15–20 LLM calls**, so the API caches per fixture per day
  (order-insensitive, keyed to the Pacific quota-reset day) and serializes
  generation behind a lock with a double-check. The cache is two-tier:
  in-memory for speed, Redis (free Upstash) for durability — free-tier
  hosting sleeps between visitors and would otherwise wipe it. A GitHub
  Action pre-generates the day's real fixtures every morning right after
  the quota reset, so visitors almost always hit cache instantly.
- **Loose version ranges broke deploys at 3 AM.** Two builds died with pip's
  `ResolutionImpossible` re-resolving the `crewai → chromadb → onnxruntime`
  graph fresh. `requirements.lock` (a full freeze, 138 pins) made builds
  deterministic; `requirements.txt` stays as the human-readable direct-deps
  list with regeneration instructions.

## Run it locally

```bash
git clone https://github.com/erikolvera/gaffer-ai.git && cd gaffer-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Key from https://aistudio.google.com — the free tier works but its daily
# per-model limits are tight; a few dollars of prepay credits removes them
# (the live demo runs on ~$5 of credits)
echo "GEMINI_API_KEY=your-key" > .env

# CLI:
python -m briefing_engine.main Mexico "South Africa" --venue "Estadio Azteca"

# Or the web app:
uvicorn briefing_engine.api:app --reload     # → http://localhost:8000
```

Offline / zero-quota mode: `BRIEFING_DATA_MODE=mock` uses canned USA/Germany
data (the original learning scaffold this project grew from).

## Deploy

**Render (free):** push to GitHub → Render → *New + → Blueprint* → pick this
repo → set `GEMINI_API_KEY` and `CACHE_REDIS_URL` (free Redis from
[upstash.com](https://upstash.com)) in the dashboard. `render.yaml` does the
rest. Without `CACHE_REDIS_URL` the app still runs — the cache is just
memory-only. (The name is deliberately not `REDIS_URL`: libraries in the
agent stack auto-detect that name and break.) Builds install
`requirements.lock` for deterministic deploys.
A `Dockerfile` is included for Railway / Fly.io / Cloud Run.

**Daily warm-up:** `.github/workflows/warm-cache.yml` pre-generates briefings
for the fixtures listed in `fixtures/schedule.json` each morning. Extend the
schedule file as the tournament progresses.

## Project structure

```
briefing_engine/
├── schemas.py   data contracts: FixtureRequest, TeamMatchData, BriefingOutput
├── tools.py     Scout's hands: grounded live search + mock fallback ladder
├── crew.py      the three agents, their tasks, and the relay wiring
├── main.py      CLI entry point
├── api.py       FastAPI: /api/briefing with two-tier cache + fallback sweeps
└── static/      the fan-facing search page
fixtures/schedule.json          real match schedule the warm-up reads
.github/workflows/warm-cache.yml  the 1:30am pre-generation robot
render.yaml · Dockerfile        deploy blueprints (Render / anywhere)
requirements.lock               full 138-pin freeze — deterministic builds
```

## Roadmap

- Stream real agent progress to the relay UI (it currently paces on typical timings)
- Fixture calendar in the UI — one click on today's real matches (the data
  already lives in fixtures/schedule.json)

---

Built by **Erik Olvera** as a deep dive into multi-agent orchestration:
the LLM is a component — the architecture is the engineering.
