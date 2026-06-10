"""
main.py — The entry point. Run with:  python -m briefing_engine.main

THE FLOW:
    1. Validate the user's request against a schema (FixtureRequest).
    2. Build the crew (the three-agent pipeline).
    3. kickoff() — hand the validated fixture into the crew as templated inputs.
    4. Inspect the result.

WHY VALIDATE FIRST?
    "Garbage in, garbage out" is expensive when each step costs an LLM call.
    We catch a malformed request HERE, cheaply, before spending any tokens.
"""

from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

# Pull GEMINI_API_KEY (and any other secrets) from .env into the environment
# BEFORE anything checks for it. .env is gitignored — secrets never get committed.
load_dotenv()

from crewai.crew import CrewOutput

from .crew import build_crew
from .schemas import BriefingOutput, FixtureRequest


def main() -> None:
    # --- Step 1: validate the user's request. If this raises, we never call an LLM.
    fixture = FixtureRequest(
        home_team="USA",
        away_team="Germany",
        venue="MetLife Stadium",
    )
    print(f"📋 Briefing requested: {fixture.home_team} vs {fixture.away_team} "
          f"@ {fixture.venue}\n")

    # --- Step 2: the API-key guard. Importing the crew needs no key; RUNNING it does.
    if not os.getenv("GEMINI_API_KEY"):
        print("⚠️  GEMINI_API_KEY is not set, so the agents can't call an LLM.")
        print("    The structure is valid and imports fine — set the key to run live:")
        print("    export GEMINI_API_KEY='...'   (free key: aistudio.google.com)\n")
        sys.exit(0)

    # --- Step 3: build and run the crew. The inputs fill the {placeholders}
    #     inside the task descriptions.
    crew = build_crew()
    result = crew.kickoff(inputs={
        "home_team": fixture.home_team,
        "away_team": fixture.away_team,
        "venue": fixture.venue,
        })
    assert isinstance(result, CrewOutput)

    briefing = result.pydantic
    assert isinstance(briefing, BriefingOutput)
    print(briefing.markdown_briefing)
    if briefing.escalated_alerts:
        print("\n⚠️  ESCALATED ALERTS:")
        for alert in briefing.escalated_alerts:
            print(f"- {alert.severity.value.upper()}: {alert.message} "
                  f"({alert.affected_player})")


if __name__ == "__main__":
    main()
