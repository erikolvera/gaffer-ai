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

from .crew import build_crew
from .schemas import FixtureRequest


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
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY is not set, so the agents can't call an LLM.")
        print("    The structure is valid and imports fine — set the key to run live:")
        print("    export OPENAI_API_KEY='sk-...'\n")
        sys.exit(0)

    # --- Step 3: build and run the crew.   >>> TODO #6 (your turn)
    crew = build_crew()
    #
    # >>> TODO #6: call crew.kickoff(...) and capture the result.
    #     Pass the fixture fields as `inputs` so CrewAI can fill the {placeholders}
    #     inside your task descriptions:
    #
    #     result = crew.kickoff(inputs={
    #         "home_team": fixture.home_team,
    #         "away_team": fixture.away_team,
    #         "venue": fixture.venue,
    #     })
    #
    # >>> TODO #7: print the final briefing. If you used output_pydantic in
    #     briefing_task, try `result.pydantic` to get a typed BriefingOutput;
    #     otherwise `result.raw` is the Markdown string. Inspect both to learn
    #     the shape of CrewAI's CrewOutput object.
    raise NotImplementedError("Complete TODO #6 and #7 to run the crew live.")


if __name__ == "__main__":
    main()
