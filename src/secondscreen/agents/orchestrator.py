"""Match orchestrator: events in, moments + overlay cues + recap out.

Routes each stats-engine signal one of three ways:
  narrative signal  -> moment workflow (Analyst -> Fact-Checker -> Persona)
  threshold signal  -> instant overlay cue, no model call (speed tags, cards, subs)
  full time         -> Recap agent
Shared state (story so far, published moments, audit trail) lives in a MatchStore.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field

from secondscreen.agents.context import build_context
from secondscreen.agents.personas import DEFAULT_PERSONAS, Persona
from secondscreen.agents.pipeline import build_moment_workflow
from secondscreen.agents.recap import write_recap
from secondscreen.agents.schemas import AnalystRequest
from secondscreen.agents.templates import INSTANT_KINDS, instant_cue, is_narrative
from secondscreen.stats.engine import StatsEngine

CASUAL_SKIP = {"distance_milestone", "elite_pass"}


@dataclass
class MatchStore:
    """In-memory shared state. Same interface is backed by Cosmos DB in the cloud."""
    match_id: str | None = None
    moments: list[dict] = field(default_factory=list)
    cues: list[dict] = field(default_factory=list)
    audit: list[dict] = field(default_factory=list)
    recap: dict | None = None

    def add_moment(self, m: dict) -> None:
        self.moments.append(m)
        self.cues.extend(m["cues"])
        self.audit.append({"moment_id": m["moment_id"], "signal_id": m["signal_id"], "source": m["source"],
                           "attempts": m["attempts"], "log": m["check_log"]})

    def add_cue(self, c: dict) -> None:
        self.cues.append(c)


class MatchOrchestrator:
    def __init__(self, client, personas: list[Persona] | None = None, store: MatchStore | None = None,
                 use_judge: bool = True, on_moment=None, on_cue=None):
        self.client = client
        self.personas = personas or DEFAULT_PERSONAS
        self.store = store or MatchStore()
        self.engine = StatsEngine()
        self.match_ref = {"match_id": None, "count": 0}
        self.workflow = build_moment_workflow(client, self.personas, self.match_ref, use_judge=use_judge)
        self.on_moment, self.on_cue = on_moment, on_cue
        self.timing: list[float] = []

    async def ingest(self, event: dict) -> None:
        for sig in self.engine.ingest(event):
            s = sig.to_dict()
            if self.match_ref["match_id"] is None:
                self.match_ref["match_id"] = self.store.match_id = self.engine.match_id
            if is_narrative(s, self.store.moments):
                await self._moment(s)
            elif s["kind"] in INSTANT_KINDS:
                self._instant(s)
            elif s["kind"] == "full_time":
                self.store.recap = await write_recap(self.client, self.engine, self.store.moments)

    async def _moment(self, s: dict) -> None:
        ctx = build_context(s, self.engine, self.store.moments)
        t0 = time.perf_counter()
        result = await self.workflow.run(AnalystRequest(s, ctx))
        self.timing.append(time.perf_counter() - t0)
        for out in result.get_outputs():
            m = asdict(out)
            self.store.add_moment(m)
            if self.on_moment:
                await self.on_moment(m)

    def _instant(self, s: dict) -> None:
        for p in self.personas:
            focus = p.focus_player and s["facts"].get("player") == p.focus_player
            if p.mode == "casual" and s["kind"] in CASUAL_SKIP and not focus:
                continue
            base = instant_cue(s, p.lang)
            if not base:
                continue
            cue = {"cue_id": f"{s['signal_id']}-{p.persona_id}", "moment_id": None, "match_id": self.engine.match_id,
                   "persona_id": p.persona_id, "lang": p.lang, "type": base["type"], "clock": s["clock"],
                   "elapsed": s["elapsed"], "duration_s": 5, "priority": s["importance"],
                   "team_id": s.get("team_id"), "player_id": s.get("player_id"),
                   "text": {"strap": base["strap"], "card": None}, "stats": base["stats"],
                   "evidence": s["evidence"], "focus": bool(focus)}
            self.store.add_cue(cue)
            if self.on_cue:
                self.on_cue(cue)

    def summary(self) -> dict:
        ms = self.store.moments
        rejections = sum(1 for a in self.store.audit for e in a["log"]
                         if e.get("step") == "fact_check" and e.get("verdict") == "rejected")
        return {
            "match_id": self.engine.match_id, "score": self.engine.score, "moments": len(ms),
            "from_agents": sum(m["source"] == "agent" for m in ms),
            "from_fallback": sum(m["source"] == "fallback" for m in ms),
            "revised": sum(m["attempts"] > 1 for m in ms), "fact_check_rejections": rejections,
            "persona_fallbacks": sum(1 for a in self.store.audit for e in a["log"] if e.get("step") == "persona_fallback"),
            "cues": len(self.store.cues), "recap_source": (self.store.recap or {}).get("source"),
            "avg_moment_seconds": round(sum(self.timing) / len(self.timing), 3) if self.timing else None,
        }
