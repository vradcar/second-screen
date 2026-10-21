"""Pick a highlights reel from a match's published moments.

Every goal and red card, then the best of the rest (big chances, saves, and the
story moments the agents explained), in match order. Each clip starts a little
before the moment, so the build-up plays, and ends once the graphics have shown.
"""
from __future__ import annotations

ALWAYS = {"goal": (18, 8), "red_card": (12, 8), "penalty_awarded": (12, 6)}
EXTRA = {"big_chance_missed": (12, 6), "big_save": (12, 6), "late_surge": (6, 10), "hot_streak": (6, 10),
         "pressing_spell": (6, 10), "fatigue_fade": (6, 10)}


def pick(moments: list[dict], limit: int = 10, persona: str = "studio_analyst") -> list[dict]:
    must = [m for m in moments if m["kind"] in ALWAYS]
    rest = sorted((m for m in moments if m["kind"] in EXTRA), key=lambda m: (-m["importance"], m["elapsed"]))
    chosen, kinds = list(must), set()
    for m in rest:
        if len(chosen) >= limit:
            break
        if any(abs(m["elapsed"] - c["elapsed"]) < 45 for c in chosen) or (m["kind"] in kinds and m["importance"] < 0.6):
            continue   # avoid two clips of the same spell, and repeats of minor kinds
        chosen.append(m)
        kinds.add(m["kind"])
    clips = []
    for m in sorted(chosen[:max(limit, len(must))], key=lambda m: m["elapsed"]):
        pre, post = ALWAYS.get(m["kind"]) or EXTRA[m["kind"]]
        r = next((r for r in m["renderings"] if r["persona_id"] == persona), m["renderings"][0])
        clips.append({"moment_id": m["moment_id"], "kind": m["kind"], "clock": m["clock"], "elapsed": m["elapsed"],
                      "start": max(m["elapsed"] - pre, 0), "end": m["elapsed"] + post, "headline": r["lower_third"]})
    return clips
