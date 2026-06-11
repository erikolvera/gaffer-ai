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
- **Gemini 3.5 Flash** (free tier) — agent reasoning + grounded Google Search
  for live team news
- **Pydantic v2** — data contracts at every boundary
- **FastAPI + vanilla JS** — one endpoint, one page; the UI animates the agent
  relay while the crew works

## Engineering notes (the parts that fought back)

- **Free-tier quotas are per model, and the docs lie.** Research said 250
  requests/day for `gemini-2.5-flash`; the API's 429 said `limit: 20`. The fix:
  model selection is env-configurable (`GEMINI_MODEL`), defaulting to the 3.x
  generation with its own, roomier bucket.
- **Cheaper models fail quietly.** On `flash-lite`, the crew ran fine — and
  silently dropped the critical alert from the structured output. The
  alert-journey test caught it. Model choice is a correctness decision, not
  just a cost one.
- **Grounding + strict JSON don't mix in one call.** Live data is fetched in
  two steps: a grounded call researches in prose, a second call structures it
  against the schema. Both paths (live and mock fallback) pass identical
  validation — web data earns no extra trust.
- **One briefing ≈ 15–20 LLM calls**, so the API caches per fixture per day
  (order-insensitive) and serializes generation behind a lock with a
  double-check. The first visitor pays ~45s; everyone else gets today's
  edition instantly, at zero quota.

## Run it locally

```bash
git clone https://github.com/erikolvera/gaffer-ai.git && cd gaffer-ai
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Free key from https://aistudio.google.com — no card needed
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
repo → set `GEMINI_API_KEY` in the dashboard. `render.yaml` does the rest.
A `Dockerfile` is included for Railway / Fly.io / Cloud Run.

## Project structure

```
briefing_engine/
├── schemas.py   data contracts: FixtureRequest, TeamMatchData, BriefingOutput
├── tools.py     Scout's hands: grounded live search + mock fallback ladder
├── crew.py      the three agents, their tasks, and the relay wiring
├── main.py      CLI entry point
├── api.py       FastAPI: /api/briefing with cache + generation lock
└── static/      the fan-facing search page
```

## Roadmap

- Stream real agent progress to the relay UI (it currently paces on typical timings)
- Persistent cache (SQLite) so briefings survive restarts
- Fixture calendar integration — one click on today's real matches

---

Built by **Erik Olvera** as a deep dive into multi-agent orchestration:
the LLM is a component — the architecture is the engineering.
