"""
tools.py — The Lead Scout's hands.

WHY THIS FILE EXISTS:
    Agents can't touch the network. When the Scout "fetches stats," the LLM
    actually emits: "call FetchTeamStatsTool with team_name='USA'". CrewAI then
    runs the Python below and feeds the result back into the conversation.

    So a "tool" is just: a validated function + a description the LLM can read.

LEARNING GOAL FOR YOU:
    The mock + error handling are done so you can study the pattern.
    The TODOs (marked >>>) are where YOU practice. Fill them in.
"""

from __future__ import annotations

import logging
from typing import Type

from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from .schemas import (
    AlertSeverity,
    PlayerStat,
    RecentForm,
    TacticalAlert,
    TeamMatchData,
    MatchResult,
)

# A real logger, not print(). In production you'd ship these to Datadog/CloudWatch.
logger = logging.getLogger("briefing_engine.tools")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")


# ---------------------------------------------------------------------------
# The mocked "api-football-v1" backend.
# In reality this would be: requests.get(f"{BASE}/teams", params=..., headers=...)
# We return canned JSON so you can build the whole system with zero API keys.
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
    # >>> TODO #1: Add a "Germany" entry to _FAKE_DB.
    #     Give it a different formation (try "4-2-3-1"), two recent_form entries,
    #     two key_players, and — importantly — ONE alert with severity "critical"
    #     (e.g. a suspended center-back). This is how you'll test that critical
    #     alerts survive the journey through all three agents.
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
