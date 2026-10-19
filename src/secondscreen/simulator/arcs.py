"""Hidden narrative arcs that bend the match's probabilities.

Arcs never appear in the event stream. They are written to a separate truth
file so we can check whether the stats engine and agents rediscover them from
the raw events alone.
"""
from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import asdict, dataclass

from secondscreen.simulator.teams import Club


@dataclass
class Arc:
    kind: str
    team_id: str
    start_min: float
    end_min: float
    player_id: str | None = None
    description: str = ""

    def active(self, minute: float) -> bool:
        return self.start_min <= minute < self.end_min

    def to_dict(self) -> dict:
        d = asdict(self)
        d["start_min"] = round(self.start_min, 1)
        d["end_min"] = round(min(self.end_min, 95.0), 1)
        return d


class ArcDirector:
    def __init__(self, rng: random.Random, home: Club, away: Club):
        self.rng = rng
        self.home, self.away = home, away
        self.arcs: list[Arc] = []
        self._late_surge_decided = False

        presser = rng.choice([home, away])
        s = rng.uniform(14, 30)
        self.arcs.append(Arc("pressing_spell", presser.team_id, s, s + rng.uniform(10, 14),
                             description=f"{presser.name} press high and aggressively"))

        star_club = rng.choice([home, away])
        attackers = sorted(
            (p for p in star_club.players if p.on_pitch and p.position in ("ST", "RW", "LW", "CM")),
            key=lambda p: p.finishing + p.dribbling, reverse=True,
        )[:3]
        star = rng.choice(attackers)
        s = rng.uniform(50, 66)
        self.arcs.append(Arc("star_takeover", star_club.team_id, s, s + rng.uniform(12, 18),
                             player_id=star.player_id,
                             description=f"{star.name} takes over the game"))

        fader = rng.choice([home, away])
        s = rng.uniform(58, 70)
        self.arcs.append(Arc("fatigue_fade", fader.team_id, s, 200,
                             description=f"{fader.name} tire and lose control late on"))

    def maybe_late_surge(self, minute: float, score: dict[str, int]) -> Arc | None:
        """At ~72', the trailing side (or a random side if level) throws everything forward."""
        if self._late_surge_decided or minute < 72:
            return None
        self._late_surge_decided = True
        h, a = self.home.team_id, self.away.team_id
        if score[h] < score[a]:
            club = self.home
        elif score[a] < score[h]:
            club = self.away
        else:
            if self.rng.random() < 0.4:
                return None
            club = self.rng.choice([self.home, self.away])
        arc = Arc("late_surge", club.team_id, minute, 200,
                  description=f"{club.name} throw everything forward")
        self.arcs.append(arc)
        return arc

    def mods(self, minute: float, team_id: str) -> tuple[defaultdict, dict]:
        """Probability modifiers for `team_id` at `minute`, plus player involvement weights."""
        m: defaultdict = defaultdict(float)
        involve: dict[str, float] = {}
        for a in self.arcs:
            if not a.active(minute):
                continue
            mine = a.team_id == team_id
            if a.kind == "pressing_spell":
                if mine:
                    m["press"] += 0.35
                    m["fatigue_rate"] += 0.5
                    m["force_block"] = "high_press"
                else:
                    m["pass_acc"] -= 0.35
            elif a.kind == "star_takeover" and mine:
                involve[a.player_id] = 3.5
                m["star_finish"] += 0.35
                m["star_dribble"] += 12
                m["star_id"] = a.player_id
            elif a.kind == "fatigue_fade" and mine:
                m["fatigue_rate"] += 0.9
                m["pass_acc"] -= 0.25
                m["press"] -= 0.08
            elif a.kind == "late_surge" and mine:
                m["press"] += 0.15
                m["shot_intent"] += 0.06
                m["directness"] += 0.15
                m["finishing"] += 0.15
                m["force_block"] = "high_press"
        return m, involve

    def to_list(self) -> list[dict]:
        return [a.to_dict() for a in self.arcs]
