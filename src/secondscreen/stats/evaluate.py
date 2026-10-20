"""Score the stats engine's pattern detectors against the simulator's hidden truth.

The simulator plants story arcs that never appear in the event feed. This
measures how often the engine rediscovers them from raw events alone, and how
often it raises a signal no arc explains.

    python -m secondscreen.stats.evaluate --seeds 60
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict

from secondscreen.simulator import simulate
from secondscreen.stats.engine import StatsEngine

# arc kind -> detector signal kind
ARC_TO_SIGNAL = {
    "pressing_spell": "pressing_spell",
    "star_takeover": "hot_streak",
    "fatigue_fade": "fatigue_fade",
    "late_surge": "late_surge",
}
SLACK_MIN = 3.0  # a detection may land up to 3 minutes either side of the arc window


def run_match(seed: int) -> tuple[StatsEngine, dict]:
    events, truth = simulate(seed)
    eng = StatsEngine()
    for ev in events:
        eng.ingest(ev)
    return eng, truth


def match_arc(arc: dict, sig) -> bool:
    if sig.team_id != arc["team_id"] or sig.status == "end":
        return False
    if arc["kind"] == "star_takeover" and sig.player_id != arc["player_id"]:
        return False
    return arc["start_min"] - SLACK_MIN <= sig.minute <= arc["end_min"] + SLACK_MIN


def explained_by_tactics(sig, truth: dict) -> bool:
    """A pressing detection is also legitimate if the team really switched into a
    high press near that time (e.g. chasing the game), even without a planted arc."""
    if sig.kind != "pressing_spell":
        return False
    for row in truth["tactical_timeline"]:
        if (row["team_id"] == sig.team_id and row["block"] == "high_press" and row["minute"] > 0
                and row["period"] == sig.period and abs(row["minute"] - sig.minute) <= 8):
            return True
    return False


def evaluate(seeds: range) -> dict:
    hits, totals = defaultdict(int), defaultdict(int)
    detections, explained = defaultdict(int), defaultdict(int)
    noise = defaultdict(list)
    for seed in seeds:
        eng, truth = run_match(seed)
        arcs = truth["arcs"]
        for arc in arcs:
            kind = ARC_TO_SIGNAL[arc["kind"]]
            totals[arc["kind"]] += 1
            if any(s.kind == kind and match_arc(arc, s) for s in eng.signals):
                hits[arc["kind"]] += 1
        for kind in set(ARC_TO_SIGNAL.values()):
            sigs = [s for s in eng.signals if s.kind == kind and s.status != "end"]
            detections[kind] += len(sigs)
            explained[kind] += sum(1 for s in sigs
                                   if any(ARC_TO_SIGNAL[a["kind"]] == kind and match_arc(a, s) for a in arcs)
                                   or explained_by_tactics(s, truth))
        for kind in ("momentum_swing", "regime_change", "pressing_spell", "hot_streak"):
            noise[kind].append(sum(1 for s in eng.signals if s.kind == kind and s.status != "end"))
    n = len(seeds)
    report = {"matches": n, "arcs": {}, "signals_per_match": {}}
    for arc_kind, sig_kind in ARC_TO_SIGNAL.items():
        report["arcs"][arc_kind] = {
            "recall": round(hits[arc_kind] / totals[arc_kind], 2) if totals[arc_kind] else None,
            "precision": round(explained[sig_kind] / detections[sig_kind], 2) if detections[sig_kind] else None,
            "arcs": totals[arc_kind],
            "detections": detections[sig_kind],
        }
    report["signals_per_match"] = {k: round(sum(v) / n, 1) for k, v in noise.items()}
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=40)
    ap.add_argument("--start", type=int, default=1000, help="held-out seeds, away from tuning seeds")
    args = ap.parse_args()
    print(json.dumps(evaluate(range(args.start, args.start + args.seeds)), indent=2))


if __name__ == "__main__":
    main()
