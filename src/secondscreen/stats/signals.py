"""Signals: the stats engine's output contract with the agent layer.

Every signal carries the event IDs and stat values that justify it. Agents may
only make claims that trace back to a signal's `facts` or `evidence`; the
Fact-Checker agent enforces that.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field

# Thresholds live in one place so they're easy to explain and tune.
THRESHOLDS = {
    "speed_alert_kmh": 33.0,        # sprint speed worth tagging on screen
    "shot_speed_kmh": 105.0,        # thunderbolt
    "big_chance_xg": 0.30,
    "elite_pass_difficulty": 6.0,   # completed passes an average player misses 60%+ of the time
    "distance_milestones_m": (5000, 10000, 12000),
    "press_ratio_on": 1.5,         # pressing intensity vs the team's own baseline
    "press_ratio_off": 1.15,
    "chaos_changes_per_min": 3.4,   # possession changes per minute in a 5-minute window
    "control_share": 0.66,          # possession share that counts as control
    "momentum_swing": 60.0,         # points on the -100..100 momentum scale
    "surge_threat_share": 0.68,
    "fade_completion_drop": 0.06,
    "hot_streak_ratio": 2.0,        # touch share vs his own earlier share
    "hot_streak_min_touches": 18,
    "hot_streak_min_decisive": 2,
}


@dataclass
class Signal:
    signal_id: str
    kind: str
    period: int
    clock: str
    minute: float
    elapsed: float
    importance: float
    team_id: str | None = None
    player_id: str | None = None
    status: str = "instant"         # instant | start | end
    facts: dict = field(default_factory=dict)
    evidence: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
