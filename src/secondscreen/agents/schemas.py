"""Structured outputs the agents must return, plus the messages that flow
between workflow executors."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pydantic import BaseModel, Field

Theme = Literal["game_state", "pressing", "momentum", "control_vs_chaos", "individual",
                "physical", "discipline", "chance_quality", "set_piece"]


# ---------------------------------------------------------------- LLM outputs
class CommentaryLine(BaseModel):
    lang: str = Field(description="Language code: en, es or fr.")
    build: str = Field(description="Play-by-play build-up before the peak, a few short bursts. May be empty.")
    peak: str = Field(description="The call itself, the loudest moment. A few words.")
    after: str = Field(description="Straight after the peak: who, and what it means (score, numbers on the pitch).")
    pundit: str = Field(description="The co-commentator's calmer analysis, one or two sentences.")
    facts: list[str] = Field(description="FACT keys behind every number or claim used.")


class Commentary(BaseModel):
    lines: list[CommentaryLine]


class Claim(BaseModel):
    text: str = Field(description="One factual sentence.")
    facts: list[str] = Field(description="Keys from the FACTS block that support this sentence.")


class MomentDraft(BaseModel):
    headline: str = Field(description="Broadcast headline, max 70 characters.")
    summary: str = Field(description="What happened, one or two sentences.")
    why_it_matters: str = Field(description="Why this moment matters for the match, one or two sentences.")
    theme: Theme
    claims: list[Claim] = Field(description="Every factual statement made above, each with its fact keys.")


class ClaimVerdict(BaseModel):
    index: int
    supported: bool
    reason: str


class JudgeVerdict(BaseModel):
    verdicts: list[ClaimVerdict]
    narrative_supported: bool = Field(description="Do the headline, summary and why_it_matters follow from the claims?")
    feedback: str = Field(description="If anything is unsupported, tell the writer exactly what to fix.")


class StatChip(BaseModel):
    label: str
    value: str


class Rendering(BaseModel):
    persona_id: str
    lang: str
    lower_third: str = Field(description="On-screen strap, max 60 characters.")
    body: str = Field(description="Second-screen card text, max 240 characters.")
    stat_chips: list[StatChip] = Field(default_factory=list, description="Up to 3 stats taken from the facts.")


class PersonaBatch(BaseModel):
    renderings: list[Rendering]


class RenderingVerdict(BaseModel):
    persona_id: str
    supported: bool
    reason: str


class PersonaVerdicts(BaseModel):
    verdicts: list[RenderingVerdict]


class RecapParagraph(BaseModel):
    text: str
    moment_ids: list[str] = Field(default_factory=list)
    facts: list[str] = Field(default_factory=list)


class Recap(BaseModel):
    title: str
    standfirst: str = Field(description="One-sentence summary under the title.")
    paragraphs: list[RecapParagraph]
    player_of_the_match: str
    player_of_the_match_reason: str
    player_of_the_match_facts: list[str] = Field(default_factory=list)


# ------------------------------------------------------- workflow messages
@dataclass
class AnalystRequest:
    signal: dict
    context: dict           # assembled facts + match state, see context.py
    attempt: int = 1
    feedback: list[str] = field(default_factory=list)
    previous: MomentDraft | None = None
    log: list[dict] = field(default_factory=list)   # audit trail across attempts


@dataclass
class CheckedDraft:
    request: AnalystRequest
    draft: MomentDraft


@dataclass
class ApprovedMoment:
    request: AnalystRequest
    draft: MomentDraft
    source: Literal["agent", "fallback"]
    check_log: list[dict] = field(default_factory=list)


@dataclass
class FailedDraft:
    request: AnalystRequest
    reasons: list[str]
    check_log: list[dict] = field(default_factory=list)


@dataclass
class PublishedMoment:
    moment_id: str
    signal_id: str
    kind: str
    clock: str
    minute: float
    elapsed: float
    team_id: str | None
    player_id: str | None
    importance: float
    source: str
    attempts: int
    draft: dict
    renderings: list[dict]
    cues: list[dict]
    evidence: list[str]
    check_log: list[dict]
    facts: dict = field(default_factory=dict)   # values of the facts the claims cite
    commentary: dict = field(default_factory=dict)   # lang -> spoken commentary script (big moments only)


@dataclass
class RenderedMoment:
    """A published moment on its way to the commentary step, with the context it was written from."""
    published: PublishedMoment
    draft: MomentDraft
    context: dict
