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

HOW THIS FILE CAME TOGETHER:
    Agent 1 (Lead Scout) was the scaffold's worked example; Agents 2 and 3
    mirror its shape with different intent. The pipeline is fan-first: the
    final hop writes for the fan who searched this fixture, not for a coach.
"""

from __future__ import annotations

import os

from crewai import Agent, Crew, LLM, Task, Process

from .tools import FetchTeamStatsTool
from .schemas import BriefingOutput

# One shared LLM for all three agents. The "gemini/" prefix selects Google's
# API via CrewAI's native Gemini client (free tier; needs GEMINI_API_KEY).
# Free-tier quotas are PER MODEL: 2.5-flash allows only 20 req/day, while the
# 3.x generation is far roomier. Override with GEMINI_MODEL if needed.
llm = LLM(model="gemini/" + os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))


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
    llm=llm,
    verbose=True,                   # prints the agent's reasoning — great for learning
    allow_delegation=False,         # this agent can't hand work to others
)

# A Task binds an instruction to an agent. The {curly_braces} are placeholders
# that main.py fills via crew.kickoff(inputs={...}). This is "context injection".
scout_task = Task(
    description=(
        """Fetch stats for the fixture: {home_team} vs {away_team} at {venue}.
        Call fetch_team_stats for '{home_team}' AND for '{away_team}'.
        Return both teams' raw JSON, and explicitly list any alerts you saw."""
    ),
    # expected_output steers the LLM toward the shape we want. It's a soft
    # contract (the hard contract is the Pydantic validation inside the tool).
    expected_output=(
        """The validated JSON for both teams, followed by a short bullet list of
        any injury/suspension alerts (or 'No alerts')."""
    ),
    agent=lead_scout,
)


# ---------------------------------------------------------------------------
# AGENT 2 — THE TACTICAL ANALYST
# ---------------------------------------------------------------------------
# This agent has NO tools. Its raw material is the Scout's output, not the API.
# That's the key lesson: an agent's "input" can be another agent's "output".
tactical_analyst = Agent(
    role="Tactical Analyst",
    goal=(""" 
    Compare formations, read the xG form,
    flag dangerous matchups, and CARRY FORWARD any critical alerts the Scout found.     
    """),
    backstory=("""
    You are an elite tactical analyst who pays attention to detail making sure the data given is used correctly. You are not to make up any information that is not given to you. You reason ONLY from the data provided to you. You never invent stats, players, or facts that aren't in it.
    """),
    tools=[],
    llm=llm,
    verbose=True,
    allow_delegation=False,
)

# context=[scout_task] is THE IMPORTANT PART — it hands the Scout's JSON to
# the Analyst. Without it, the Analyst sees nothing.
analysis_task = Task(
    description= ("""
    You receive a JSON package of match data for both teams from the Scout. 
    Your job is to analyze this data and produce a tactical analysis for the  
    Sports Journalist. You must:
      - Compare the formations and suggest likely matchups.
      - Analyze the recent form (xG over the recent form provided) for both teams.
      - Identify any "dangerous" player-vs-player matchups.
      - CARRY FORWARD any 'critical' alerts from the Scout (e.g. "Key Defender Injured").
    Do not invent stats or players — reason only from the JSON provided.
    """),
    expected_output = ("""
    A tactical report with sections: Formation Matchup, Form Comparison
    (xG trends), Dangerous Matchups, and ALERTS — reproducing any
    'critical' alert from the Scout verbatim, or stating 'No critical alerts'.
    """),
    agent=tactical_analyst,
    context=[scout_task],
)


# ---------------------------------------------------------------------------
# AGENT 3 — THE SPORTS JOURNALIST
# ---------------------------------------------------------------------------
# The presentation hop — and where fan-first lives: turn the analysis into a
# Markdown match preview for the fan who searched this fixture.
sports_journalist = Agent(
    role="Sports Journalist",
    goal="""
    Turn tactical analysis into a compelling match preview for the fans who
    searched this fixture — from die-hards to first-time viewers — leaving
    them excited and informed.
    """,
    backstory="""
    You are a busy pro sports journalist who never buries an alert below
    the fold: big team news (injuries, suspensions) is the headline a fan
    must not miss. You are crisp, engaging, and confident, but strictly
    grounded in the analysis you receive. You never invent stats or claim
    knowledge beyond the provided data.
    """,
    tools=[],
    llm=llm,
    verbose=True,
    allow_delegation=False,
)

briefing_task = Task(
    description=("""
    You are given the tactical analysis from the Tactical Analyst for a fixture.
    Turn it into a high-quality match preview for the fans who searched this
    fixture — engaging for die-hards, welcoming for first-time viewers.
    Non-negotiable: any 'critical' alert from the analysis must appear BOTH
    in the ALERTS section of the Markdown AND in the escalated_alerts list.
    """),
    expected_output=("""
    A Markdown preview with sections: Fixture, Form, Key Matchups,
    ALERTS, What to Watch For. Alongside it: the fixture name (e.g.
    'USA vs Germany') and an escalated_alerts list containing every
    'critical' alert from the analysis with its severity, message,
    and affected_player — or an empty list if there are none.
    """),
    output_pydantic=BriefingOutput,
    agent=sports_journalist,
    context=[analysis_task],
)


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
            tactical_analyst,
            sports_journalist,
        ],
        tasks=[
            scout_task,
            analysis_task,
            briefing_task,
        ],
        process=Process.sequential,
        verbose=True,
    )
