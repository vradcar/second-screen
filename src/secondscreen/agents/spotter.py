"""The spotter: instant commentary calls, timed to land on the action.

Real TV commentators call a goal as it happens and the analysis comes after. The agent
chain (analyst, fact-checker, personas, commentator) takes several seconds, so on a live
stream its commentary would arrive after the goal. The spotter closes that gap: it runs
its own copy of the stats engine on the feed, which reaches the server a few seconds
before viewers see it (the broadcast delay), and the moment the engine flags a goal,
red card or big chance it sends the call: build-up, peak and landing line, from the
commentary templates (deterministic, grounded in the same facts the agents see).

The viewer's commentary box times the build-up so the peak lands as the ball goes in.
When the agents' moment for the same signal arrives, only the co-commentator's analysis
is played: the call has already been made.
"""
from __future__ import annotations

from secondscreen.agents.commentary import template_line
from secondscreen.agents.context import build_context
from secondscreen.stats.engine import StatsEngine

CALLED = {"goal", "red_card", "big_save", "big_chance_missed", "penalty_awarded"}
CALL_LEAD_WALL = 4.0   # seconds of wall time the call needs ahead of the action


def call_lead(speed: float, minimum: float) -> float:
    """How far ahead of air (in match seconds) events must be seen to call them on time."""
    return max(minimum, CALL_LEAD_WALL * speed)


class Spotter:
    def __init__(self, langs: list[str]):
        self.engine = StatsEngine()
        self.langs = langs
        self.turns: dict[str, int] = {}

    def feed(self, ev: dict) -> list[dict]:
        calls = []
        for sig in self.engine.ingest(ev):
            s = sig.to_dict()
            if s["kind"] not in CALLED:
                continue
            facts = build_context(s, self.engine, [])["facts"]
            turn = self.turns[s["kind"]] = self.turns.get(s["kind"], -1) + 1
            lines = {}
            for lang in self.langs:
                ln = template_line(s["kind"], facts, lang, "", turn)
                lines[lang] = ln.model_dump() | {"pundit": "", "source": "spotter"}
            calls.append({"signal_id": s["signal_id"], "kind": s["kind"], "at": s["elapsed"], "clock": s["clock"],
                          "commentary": lines})
        return calls
