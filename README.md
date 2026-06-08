# World Cup Tactical Briefing Engine ⚽

A **learning project** for multi-agent AI engineering with [CrewAI](https://docs.crewai.com).
Three specialized agents cooperate to turn a match fixture into a manager's tactical briefing.

> This repo is a **scaffold with deliberate gaps** (`>>> TODO #N`). The fundamentals are
> demonstrated in fully-written reference code; you complete the agent logic to learn by doing.

---

## The 8 terms to know

| Term | What it means | Where it lives here |
|------|---------------|---------------------|
| **Agent** | An LLM + role/goal/backstory + tools, running a reason→act loop | `crew.py` |
| **Tool** | A Python function the agent is *allowed* to call | `tools.py` → `FetchTeamStatsTool` |
| **Task** | A unit of work for an agent (`description` + `expected_output`) | `crew.py` |
| **Crew** | The orchestrator running tasks in order | `crew.py` → `build_crew()` |
| **Context passing** | One task's output becomes the next task's input (`context=[...]`) | `crew.py` TODO #3b |
| **Backstory** | Persona text that becomes the agent's system prompt | each `Agent(...)` |
| **Structured output** | Forcing data into a typed schema instead of free text | `schemas.py` |
| **Orchestration** | The control flow connecting it all — *your code*, not the LLM | `crew.py` |

## Data flow

```
USER REQUEST ──▶ build_crew() (sequential)
                     │
   Lead Scout ──JSON──▶ Tactical Analyst ──analysis──▶ Sports Journalist ──▶ Markdown
       │                                                                      briefing
       └─ calls tools.py ──requests──▶ api-football-v1 (mocked)
                  │
                  └─ validates with schemas.py  ← the contract every layer trusts
```

## Directory map

```
world_cup_2026/
├── briefing_engine/
│   ├── schemas.py   ✅ reference — fully written (study this for "good")
│   ├── tools.py     🔨 scaffold — TODO #1, #2
│   ├── crew.py      🔨 scaffold — TODO #3, #4, #5
│   └── main.py      🔨 scaffold — TODO #6, #7
├── requirements.txt
└── README.md
```

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Imports & validates with NO key (proves the structure is sound):
python -c "from briefing_engine import schemas, tools, crew, main; print('ok')"

# Run live (after you finish the TODOs + set a key):
export OPENAI_API_KEY='sk-...'
python -m briefing_engine.main
```

## Your learning checklist

Work them in order — each builds on the last:

- [ ] **TODO #1** (`tools.py`) — add a `Germany` entry to `_FAKE_DB` with a **critical** alert
- [ ] **TODO #2** (`tools.py`) — handle Pydantic validation errors gracefully (no crash)
- [ ] **TODO #3** (`crew.py`) — write the **Tactical Analyst** agent + task; wire `context=[scout_task]`
- [ ] **TODO #4** (`crew.py`) — write the **Sports Journalist** agent + task; try `output_pydantic=BriefingOutput`
- [ ] **TODO #5** (`crew.py`) — register both new agents/tasks in `build_crew()`
- [ ] **TODO #6** (`main.py`) — call `crew.kickoff(inputs=...)`
- [ ] **TODO #7** (`main.py`) — inspect the result (`result.raw` vs `result.pydantic`)

**Goal to prove you understand it:** trace the *critical alert* from the Germany mock data all
the way to `BriefingOutput.escalated_alerts`. If it survives every hop, you've understood
context passing — the core of multi-agent systems.
