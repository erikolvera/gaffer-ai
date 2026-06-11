"""
tools.py — The Lead Scout's hands.

WHY THIS FILE EXISTS:
    Agents can't touch the network. When the Scout "fetches stats," the LLM
    actually emits: "call FetchTeamStatsTool with team_name='USA'". CrewAI then
    runs the Python below and feeds the result back into the conversation.

    So a "tool" is just: a validated function + a description the LLM can read.

DATA SOURCES:
    Live mode (default) researches any team via Gemini grounded search;
    _FAKE_DB is the offline/dev fallback (BRIEFING_DATA_MODE=mock) and the
    fixture data for tests — its Germany entry carries the critical alert
    used to verify the alert relay end-to-end.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Type

from crewai.tools import BaseTool
from google import genai
from google.genai import types as genai_types
from pydantic import BaseModel, Field

from .schemas import (
    AlertSeverity,
    PlayerStat,
    RecentForm,
    TacticalAlert,
    TeamMatchData,
    MatchResult,
)

def _gemini_model() -> str:
    """Resolve the model at CALL time, not import time. GEMINI_MODEL_ACTIVE is
    set by build_crew() when the API falls back to an alternate model, so the
    tool's own LLM calls follow the crew onto the working model."""
    return os.getenv("GEMINI_MODEL_ACTIVE") or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")


def _model_chain() -> list[str]:
    """Models to try for grounded search, in order. Quotas — including the
    SEPARATE grounding quota — are per model, so a 429 on one model says
    nothing about the next. The 2.5 generation sits last as the workhorse
    fallback: older, less congested, with its own grounding budget."""
    fallbacks = [m.strip() for m in os.getenv(
        "GEMINI_FALLBACK_MODELS",
        "gemini-3-flash-preview,gemini-2.5-flash",
    ).split(",") if m.strip()]
    chain = [_gemini_model(), *fallbacks, "gemini-2.5-flash-lite"]
    return list(dict.fromkeys(chain))  # dedupe, keep order

# A real logger, not print(). In production you'd ship these to Datadog/CloudWatch.
logger = logging.getLogger("briefing_engine.tools")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ---------------------------------------------------------------------------
# The mocked "api-football-v1" backend.
# In reality this would be: requests.get(f"{BASE}/teams", params=..., headers=...)
# Canned JSON keeps dev and tests runnable with zero API keys or quota.
# ---------------------------------------------------------------------------
_FAKE_DB: dict[str, dict] = {
    "USA": {
        "team_id": 1,
        "team_name": "USA",
        "formation": "4-3-3",
        "recent_form": [
            {"opponent": "Mexico", "result": "W", "score": "2-0",
             "expected_goals_for": 1.8, "expected_goals_against": 0.6},
            {"opponent": "Canada", "result": "D", "score": "1-1",
             "expected_goals_for": 1.1, "expected_goals_against": 1.2},
        ],
        "key_players": [
            {"name": "C. Pulisic", "position": "LW", "goals": 3,
             "assists": 2, "minutes_played": 270, "is_available": True},
            {"name": "W. McKennie", "position": "CM", "goals": 1,
             "assists": 1, "minutes_played": 250, "is_available": True},
        ],
        "alerts": [],
    },
    # Germany carries the one CRITICAL alert on purpose: USA vs Germany in
    # mock mode is the end-to-end test that an alert survives the journey
    # through all three agents into BriefingOutput.escalated_alerts.
    "Germany": {
        "team_id" : 2,
        "team_name" : "Germany",
        "formation" : "4-2-3-1",
        "recent_form" : [
            {"opponent": "USA", "result": "W", "score": "2-1",
             "expected_goals_for" : 2.2, "expected_goals_against" : 0.8},
            {"opponent": "Finland", "result": "W", "score": "4-0",
             "expected_goals_for" : 4.5, "expected_goals_against" : 0.6}
        ],
        "key_players" : [
            {"name": "K. Havertz", "position": "ST", "goals": 1,
             "assists": 1, "minutes_played" : 270, "is_available" : True},
            {"name": "J. Kimmich", "position": "RB", "goals": 0,
             "assists" : 2, "minutes_played" : 270, "is_available" : True}
        ],
        "alerts" : [
            {"severity": "critical", "message": "Undav is injured", "affected_player": "Undav"}
        ]
    }
}


def _call_api(team_name: str) -> dict:
    """
    Simulates a single HTTP GET against api-football-v1.

    Notice the explicit error BOUNDARY: anything that goes wrong with the
    "network" is converted into one clear exception type the caller can handle.
    """
    logger.info("GET /teams?name=%s  (mocked)", team_name)
    record = _FAKE_DB.get(team_name)
    if record is None:
        # Simulate a 404 from the real API.
        raise KeyError(f"api-football-v1 returned no team named '{team_name}'")
    return record


def _search_live_stats(team_name: str) -> dict:
    """
    Fetch CURRENT stats for any team via Gemini's Grounding with Google Search.

    Two-step pattern (grounding and strict JSON output don't mix in one call):
      1. RESEARCH — a grounded call searches the live web and returns prose notes.
      2. STRUCTURE — a second call converts those notes into JSON matching
         TeamMatchData (enforced by response_schema).

    The caller still validates the result against TeamMatchData, same as the
    mock path — live data gets no special trust.

    Tries each model in _model_chain(): the grounding quota is per model and
    SEPARATE from the generation quota, so the crew's model being healthy
    doesn't guarantee this call is.
    """
    client = genai.Client()  # reads GEMINI_API_KEY from the environment

    last_err: Exception | None = None
    for model in _model_chain():
        try:
            logger.info("Grounded search for %s (live, %s)", team_name, model)
            research = client.models.generate_content(
                model=model,
                contents=(
                    f"Research the {team_name} national football team for the 2026 FIFA "
                    "World Cup, as of today. Find: their current typical formation; their "
                    "last 2-3 competitive match results (opponent, result, score, and "
                    "expected goals for/against if reported — estimate sensibly if not); "
                    "2-3 key players with position, recent goals, assists, and minutes "
                    "played; and any CURRENT injuries or suspensions affecting the squad."
                ),
                config=genai_types.GenerateContentConfig(
                    tools=[genai_types.Tool(google_search=genai_types.GoogleSearch())],
                ),
            )

            structured = client.models.generate_content(
                model=model,
                contents=(
                    "Convert these research notes into JSON for the team "
                    f"'{team_name}'. Use any positive integer for team_id. Formation "
                    "must look like '4-3-3'. For alerts, set affected_player to the "
                    "player's name and grade severity honestly: 'critical' ONLY for "
                    "players ruled out or in serious doubt for the tournament, "
                    "'warning' for knocks and minor doubts, 'info' for the rest. "
                    "Include at most the 4 most relevant alerts.\n\nNOTES:\n"
                    + (research.text or "")
                ),
                config=genai_types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=TeamMatchData,
                ),
            )
            return json.loads(structured.text or "{}")
        except Exception as e:
            last_err = e
            logger.warning("Grounded search on %s failed (%s); trying next model",
                           model, str(e)[:120])
    raise last_err if last_err else RuntimeError("empty model chain")


# ---------------------------------------------------------------------------
# The CrewAI tool itself.
# ---------------------------------------------------------------------------
class FetchTeamStatsInput(BaseModel):
    """Schema for the tool's ARGUMENTS. The LLM must fill these to call us."""
    team_name: str = Field(..., description="Exact team name, e.g. 'USA' or 'Germany'")


class FetchTeamStatsTool(BaseTool):
    # These three lines ARE the prompt the agent reads. Write them for the LLM.
    name: str = "fetch_team_stats"
    description: str = (
        "Fetch structured match stats (formation, recent xG form, key players, "
        "and injury/suspension alerts) for ONE national team by name. "
        "Call once per team."
    )
    args_schema: Type[BaseModel] = FetchTeamStatsInput

    def _run(self, team_name: str) -> str:
        """
        The actual execution. Returns a STRING because that's what gets fed
        back into the LLM's context. We validate with Pydantic first, then
        serialize — so the agent only ever sees clean, contract-conformant data.
        """
        try:
            # Live grounded search by default; BRIEFING_DATA_MODE=mock forces the
            # canned _FAKE_DB (offline dev / tests / zero-quota demos).
            if os.getenv("BRIEFING_DATA_MODE", "live") == "mock":
                raw = _call_api(team_name)
            else:
                try:
                    raw = _search_live_stats(team_name)
                except Exception as live_err:
                    # Live path down (no key, quota, 503...) — mock keeps the
                    # crew alive for teams we have canned data for.
                    logger.warning("Live lookup for '%s' failed (%s); "
                                   "falling back to mock", team_name, live_err)
                    raw = _call_api(team_name)
            # The critical line: validate the raw payload against our contract.
            # If the API/mock returned junk, THIS is where we find out — loudly.
            validated = TeamMatchData(**raw)
            logger.info("Validated %d alerts for %s",
                        len(validated.alerts), validated.team_name)
            return validated.model_dump_json(indent=2)

        except KeyError as e:
            # Team not found — give the LLM a usable error it can reason about.
            logger.warning("Lookup failed: %s", e)
            return f"ERROR: {e}"

        except Exception as e:
            # Pydantic validation failed: the mock/API returned data that
            # violates our TeamMatchData contract. Don't crash the crew — log it
            # and hand the agent a readable error it can reason about.
            logger.error("Validation failed for '%s': %s", team_name, e)
            return f"ERROR: Invalid data for '{team_name}' - {e}"
