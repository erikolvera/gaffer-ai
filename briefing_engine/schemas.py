"""
schemas.py — The data contracts for the Tactical Briefing Engine.

WHY THIS FILE EXISTS:
    In an agentic system, data flows LLM -> tool -> LLM -> tool... Each hop is a
    chance for the data to drift into garbage (an LLM might invent a formation,
    a flaky API might return null). Pydantic models are our "border control":
    nothing passes between layers unless it matches the declared shape.

    Think of every class here as a PROMISE. If `TeamMatchData` validates, then
    every field below is guaranteed to exist and have the right type. The
    Tactical Analyst can then trust the data instead of defensively re-checking.

Key term: "structured output" = forcing a probabilistic LLM (or a messy API)
to conform to a typed schema. This is the heart of software-first AI engineering.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums — closed sets of allowed values.
# Using an Enum (instead of a free string) means an invalid status is a *crash
# at the border*, not a silent bug three agents later.
# ---------------------------------------------------------------------------
class MatchResult(str, Enum):
    WIN = "W"
    DRAW = "D"
    LOSS = "L"


class AlertSeverity(str, Enum):
    """How urgently the Tactical Analyst must react to an alert."""
    INFO = "info"
    WARNING = "warning"      # e.g. key player doubtful
    CRITICAL = "critical"    # e.g. star striker out / red-card suspension


# ---------------------------------------------------------------------------
# Leaf models — the smallest building blocks.
# ---------------------------------------------------------------------------
class PlayerStat(BaseModel):
    """One player's tournament-relevant numbers."""
    name: str
    position: str = Field(..., description="e.g. 'ST', 'CB', 'CDM'")
    goals: int = Field(0, ge=0)              # ge=0 -> can't be negative
    assists: int = Field(0, ge=0)
    minutes_played: int = Field(0, ge=0)
    is_available: bool = Field(True, description="False if injured/suspended")


class RecentForm(BaseModel):
    """A single past result feeding 'form' analysis."""
    opponent: str
    result: MatchResult
    score: str = Field(..., description="e.g. '2-1'")
    expected_goals_for: float = Field(..., ge=0, description="xG the team created")
    expected_goals_against: float = Field(..., ge=0)


class TacticalAlert(BaseModel):
    """
    The 'critical alert' the prompt asks us to pass seamlessly through context.
    This is the object that must survive the Scout -> Analyst hop intact.
    """
    severity: AlertSeverity
    message: str
    affected_player: Optional[str] = None


# ---------------------------------------------------------------------------
# Composite model — what the Lead Scout's TOOL returns for ONE team.
# ---------------------------------------------------------------------------
class TeamMatchData(BaseModel):
    """The structured payload our mocked api-football-v1 returns per team."""
    team_id: int
    team_name: str
    formation: str = Field(..., description="e.g. '4-3-3'")
    recent_form: list[RecentForm] = Field(default_factory=list)
    key_players: list[PlayerStat] = Field(default_factory=list)
    alerts: list[TacticalAlert] = Field(default_factory=list)

    @field_validator("formation")
    @classmethod
    def formation_must_look_like_a_formation(cls, v: str) -> str:
        # A tiny domain rule: a formation is digits separated by dashes.
        # This is the kind of cheap guardrail that catches LLM/API nonsense early.
        parts = v.split("-")
        if not all(p.isdigit() for p in parts) or len(parts) < 2:
            raise ValueError(f"'{v}' is not a valid formation like '4-3-3'")
        return v


# ---------------------------------------------------------------------------
# Top-level fixture models — the user's REQUEST and the final DELIVERABLE.
# ---------------------------------------------------------------------------
class FixtureRequest(BaseModel):
    """What the user hands the system. The entry-point validates against this."""
    home_team: str
    away_team: str
    venue: str
    kickoff: Optional[datetime] = None


class BriefingOutput(BaseModel):
    """
    The Sports Journalist's final, validated deliverable.
    Forcing the final answer into a schema means even the 'creative writing'
    step can't skip required sections.
    """
    fixture: str = Field(..., description="e.g. 'USA vs Germany'")
    markdown_briefing: str = Field(..., min_length=50)
    escalated_alerts: list[TacticalAlert] = Field(
        default_factory=list,
        description="Critical alerts carried all the way through the crew.",
    )

    @field_validator("markdown_briefing")
    @classmethod
    def headings_must_start_lines(cls, v: str) -> str:
        # LLMs in JSON mode sometimes emit the whole document on ONE line.
        # Markdown only treats '#'/'##' as headings at line start — mid-line
        # they render as literal hash marks (and the first '# ' swallows the
        # entire text into a single giant <h1>). Re-break the lines here so
        # every consumer (API, CLI, cache) gets renderable Markdown.
        v = re.sub(r"(?<=[^\n])\s+(#{1,4} )", r"\n\n\1", v)
        # Second pass: split '## Section: body...' so the body isn't rendered
        # as part of the heading. The {1,40} bound keeps this from firing on
        # ordinary sentences that merely contain a colon.
        return re.sub(r"^(#{1,4} [^:\n]{1,40}):[ \t]+", r"\1\n\n", v, flags=re.M)


__all__ = [
    "MatchResult", "AlertSeverity", "PlayerStat", "RecentForm",
    "TacticalAlert", "TeamMatchData", "FixtureRequest", "BriefingOutput",
]
