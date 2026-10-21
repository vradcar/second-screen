"""Context engineering: turn a signal + engine state into a flat, citable FACTS table.

Agents never see raw state. They see `key = value` lines and must cite the keys
behind every claim, which is what makes the Fact-Checker's job mechanical.
"""
from __future__ import annotations

from typing import Any

from secondscreen.stats.engine import StatsEngine

TEAM_KEYS = ("goals", "xg", "shots", "shots_on_target", "big_chances", "possession_pct", "field_tilt_pct",
             "pass_completion", "ppda", "high_turnovers", "pressures", "box_entries", "players_on_pitch")
PLAYER_KEYS = ("name", "position", "goals", "assists", "shots", "xg", "key_passes", "passes",
               "pass_completion", "dribbles", "tackles_won", "interceptions", "distance_m", "top_speed_kmh")


def flatten(obj: Any, prefix: str, out: dict[str, Any]) -> dict[str, Any]:
    if isinstance(obj, dict):
        for k, v in obj.items():
            flatten(v, f"{prefix}.{k}" if prefix else str(k), out)
    elif isinstance(obj, (list, tuple)):
        if all(not isinstance(v, (dict, list)) for v in obj):
            out[prefix] = ", ".join(str(v) for v in obj)
    elif obj is not None:
        out[prefix] = round(obj, 3) if isinstance(obj, float) else obj
    return out


def build_context(signal: dict, engine: StatsEngine, story: list[dict]) -> dict:
    """Facts for one signal. `story` is the list of already-published moments."""
    facts: dict[str, Any] = {}
    flatten(signal.get("facts", {}), "signal", facts)
    facts["signal.kind"] = signal["kind"]
    facts["match.clock"] = signal["clock"]
    facts["match.minute"] = int(signal["minute"])
    facts["match.period"] = signal["period"]
    facts["match.minutes_remaining"] = max(0, 90 - int(signal["minute"]))
    names = {t: s.name for t, s in engine.teams.items()}
    for t, n in names.items():
        facts[f"team.{t}.name"] = n
        facts[f"match.score.{t}"] = engine.score.get(t, 0)
    if signal.get("team_id"):
        facts["signal.team"] = names[signal["team_id"]]
    summary = engine.team_summary()
    for t, s in summary.items():
        for k in TEAM_KEYS:
            if s.get(k) is not None:
                facts[f"stats.{t}.{k}"] = s[k]
    facts["match.momentum"] = round(engine.momentum, 1)
    facts["match.momentum_favours"] = (names[engine.home] if engine.momentum > 15 else
                                       names[engine.away] if engine.momentum < -15 else "neither side")
    facts["match.regime"] = engine.regime.replace("control:", "control by ")
    if signal.get("player_id"):
        p = engine.player(signal["player_id"])
        if p:
            d = p.to_dict()
            for k in PLAYER_KEYS:
                if d.get(k) is not None:
                    facts[f"player.{k}"] = round(d[k], 2) if isinstance(d[k], float) else d[k]
    roster = sorted(p.name for t in engine.teams.values() for p in t.players.values())
    return {
        "facts": facts,
        "story_so_far": [f"{m['clock']} {m['draft']['headline']}" for m in story[-6:]],
        "roster": roster,
        "teams": list(names.values()),
    }


def facts_block(facts: dict[str, Any]) -> str:
    return "\n".join(f"{k} = {v}" for k, v in facts.items())
