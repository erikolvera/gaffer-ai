"""
crew.py — The orchestrator. Where three agents become a pipeline.

THE BIG IDEA (read me):
    A "Crew" is just a controlled sequence of (Agent + Task) steps that YOU wire
    together in code. The LLM is smart *inside* each step; you are in charge of
    the *order* and *what flows between steps*. That control flow is the whole
    job of an AI engineer — the model is a component, not the architect.

    The triangle you must understand:

        AGENT  = who is acting   (role/goal/backstory = its system prompt)
        TASK   = what to do      (description + expected_output)
        TOOL   = what it can call (Python functions; here, FetchTeamStatsTool)

    And the connective tissue:

        context=[earlier_task]   = how a later task RECEIVES an earlier output.

LEARNING GOALS FOR YOU (the >>> TODOs):
    Agent 1 (Lead Scout) is fully written below as your worked example.
    You will write Agents 2 and 3 by copying its shape and changing the intent.
"""

from __future__ import annotations

from crewai import Agent, Crew, Task, Process

from .tools import FetchTeamStatsTool


# ---------------------------------------------------------------------------
# AGENT 1 — THE LEAD SCOUT  (fully written: study this, then mirror it)
# ---------------------------------------------------------------------------
# role/goal/backstory are NOT comments — they are the prompt the LLM reads to
# decide how to behave. Write them like a job description for a real scout.
lead_scout = Agent(
    role="Lead Scout",
    goal=(
        """Retrieve complete, accurate match stats for BOTH teams in the fixture
        by calling the fetch_team_stats tool once per team, and surface any 
        injury or suspension alerts you find."""
    ),
    backstory=(
        """You are a meticulous data scout for a national team. You never guess 
        numbers — you ALWAYS fetch them with your tool. If the tool returns an 
        error, you report it plainly rather than inventing data."""
    ),
    tools=[FetchTeamStatsTool()],   # <-- the agent's ONLY way to get real data
    verbose=True,                   # prints the agent's reasoning — great for learning
    allow_delegation=False,         # this agent can't hand work to others
)

# A Task binds an instruction to an agent. The {curly_braces} are placeholders
# that main.py fills via crew.kickoff(inputs={...}). This is "context injection".
scout_task = Task(
    description=(
        "Fetch stats for the fixture: {home_team} vs {away_team} at {venue}. "
        "Call fetch_team_stats for '{home_team}' AND for '{away_team}'. "
        "Return both teams' raw JSON, and explicitly list any alerts you saw."
    ),
    # expected_output steers the LLM toward the shape we want. It's a soft
    # contract (the hard contract is the Pydantic validation inside the tool).
    expected_output=(
        "The validated JSON for both teams, followed by a short bullet list of "
        "any injury/suspension alerts (or 'No alerts')."
    ),
    agent=lead_scout,
)


# ---------------------------------------------------------------------------
# AGENT 2 — THE TACTICAL ANALYST   >>> TODO #3 (your turn)
# ---------------------------------------------------------------------------/
# This agent has NO tools. Its raw material is the Scout's output, not the API.
# That's the key lesson: an agent's "input" can be another agent's "output".
#
# >>> TODO #3a: Define `tactical_analyst = Agent(...)`.
#     - role: "Tactical Analyst"
#     - goal: compare formations, read the xG form, flag dangerous matchups,
#             and CARRY FORWARD any critical alerts the Scout found.
#     - backstory: a sharp analyst who reasons only from the data given.
#     - tools=[]  (none — it thinks, it doesn't fetch)
tactical_analyst = Agent(
    role="Tactical Analyst",
    goal=("""
    """),
    backstory=("""
    """),
    tools=[],
    verbose=True,
    allow_delegation=False,
)
#
# >>> TODO #3b: Define `analysis_task = Task(...)` and — THE IMPORTANT PART —
#     pass `context=[scout_task]`. THIS is what hands the Scout's JSON to the
#     Analyst. Without it, the Analyst sees nothing. Set agent=tactical_analyst.
#     In the description, instruct it to preserve any 'critical' alert verbatim.


# ---------------------------------------------------------------------------
# AGENT 3 — THE SPORTS JOURNALIST   >>> TODO #4 (your turn)
# ---------------------------------------------------------------------------
# >>> TODO #4a: Define `sports_journalist = Agent(...)` (role/goal/backstory,
#     tools=[]). Its job is presentation: turn the analysis into a clean
#     Markdown manager's briefing.
#
# >>> TODO #4b: Define `briefing_task = Task(...)` with context=[analysis_task]
#     so it receives the Analyst's work. In expected_output, describe a Markdown
#     doc with sections (Fixture, Form, Key Matchups, ALERTS, Recommendation).
#     OPTIONAL ADVANCED: set `output_pydantic=BriefingOutput` to force the final
#     answer to validate against your schema (import it from .schemas).


# ---------------------------------------------------------------------------
# THE CREW — assembling the pipeline.
# ---------------------------------------------------------------------------
def build_crew() -> Crew:
    """
    Returns the fully wired Crew.

    Process.sequential means: run scout_task, THEN analysis_task, THEN
    briefing_task — in that exact order. That ordering is YOUR orchestration
    decision, expressed in code. (The other mode, hierarchical, adds a manager
    agent that decides order dynamically — ignore it until you're comfortable.)

    The "critical alert" journey you must preserve:
        scout_task output  ->  analysis_task (via context)  ->
        briefing_task (via context)  ->  BriefingOutput.escalated_alerts
    """
    return Crew(
        agents=[
            lead_scout,
            # >>> TODO #5: add tactical_analyst and sports_journalist here,
            #     in order, once you've defined them above.
        ],
        tasks=[
            scout_task,
            # >>> TODO #5 (cont.): add analysis_task and briefing_task here.
        ],
        process=Process.sequential,
        verbose=True,
    )
