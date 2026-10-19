"""Command line: generate a match, scan seeds for drama, or replay a match as a live stream.

    python -m secondscreen.simulator generate --seed 42
    python -m secondscreen.simulator scan --seeds 300 --top 10
    python -m secondscreen.simulator replay data/match_SS00042.jsonl --speed 20
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from secondscreen.simulator.engine import simulate


def write_match(seed: int, out_dir: Path) -> tuple[Path, Path, dict]:
    events, truth = simulate(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    ev_path = out_dir / f"match_{events[0]['match_id']}.jsonl"
    truth_path = out_dir / f"match_{events[0]['match_id']}.truth.json"
    with ev_path.open("w") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    truth_path.write_text(json.dumps(truth, indent=2))
    return ev_path, truth_path, truth


def drama_score(truth: dict) -> tuple[float, dict]:
    """Score how good a match is for a demo: goals, lead changes, late drama, comebacks."""
    goals = sorted(truth["goals"], key=lambda g: (g["period"], g["minute"]))
    teams = list(truth["final_score"])
    score = {t: 0 for t in teams}
    leader, lead_changes, max_deficit = None, 0, {t: 0 for t in teams}
    for g in goals:
        score[g["team_id"]] += 1
        a, b = teams
        new_leader = a if score[a] > score[b] else b if score[b] > score[a] else None
        if new_leader and leader and new_leader != leader:
            lead_changes += 1
        if new_leader:
            leader = new_leader
        for t in teams:
            other = b if t == a else a
            max_deficit[t] = max(max_deficit[t], score[other] - score[t])
    final = truth["final_score"]
    comeback = any(max_deficit[t] >= 1 and final[t] >= final[[o for o in teams if o != t][0]] for t in teams)
    late = sum(1 for g in goals if g["period"] == 2 and g["minute"] >= 75)
    n = len(goals)
    reds = sum(1 for c in truth["cards"] if c["card"] == "second_yellow")
    s = min(n, 6) * 1.0 + lead_changes * 2.5 + late * 1.5 + (3 if comeback else 0) + reds * 0.5
    if n > 6:
        s -= (n - 6) * 1.5  # too many goals looks fake
    return s, {"goals": n, "lead_changes": lead_changes, "late_goals": late, "comeback": comeback,
               "reds": reds, "final": final}


def cmd_generate(args) -> None:
    ev_path, truth_path, truth = write_match(args.seed, Path(args.out))
    print(f"events -> {ev_path}")
    print(f"truth  -> {truth_path}")
    print(f"final score: {truth['final_score']}")
    for a in truth["arcs"]:
        print(f"  arc: {a['kind']:15s} {a['team_id']} {a['start_min']:>5}' - {a['end_min']:>5}'  {a['description']}")


def cmd_scan(args) -> None:
    rows = []
    for seed in range(args.start, args.start + args.seeds):
        _, truth = simulate(seed)
        s, info = drama_score(truth)
        rows.append((s, seed, info))
    rows.sort(key=lambda r: -r[0])
    for s, seed, info in rows[: args.top]:
        print(f"seed {seed:5d}  drama {s:5.1f}  {info}")


def cmd_replay(args) -> None:
    """Emit events to stdout in (scaled) real time. Swap the sink for Event Hubs later."""
    path = Path(args.path)
    prev = None
    for line in path.open():
        e = json.loads(line)
        t = e["elapsed_seconds"]
        if prev is not None and args.speed > 0:
            time.sleep(max(0.0, (t - prev) / args.speed))
        prev = t
        if args.compact:
            who = e.get("player_name", "")
            extra = e.get("outcome", "")
            print(f"{e['clock']:>7} {e['type']:<18} {e.get('team_id', ''):<4} {who:<20} {extra}", flush=True)
        else:
            sys.stdout.write(line)
            sys.stdout.flush()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.simulator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="simulate one match to JSONL + truth file")
    g.add_argument("--seed", type=int, default=7)
    g.add_argument("--out", default="data")
    g.set_defaults(func=cmd_generate)

    s = sub.add_parser("scan", help="find seeds that produce dramatic matches")
    s.add_argument("--seeds", type=int, default=200)
    s.add_argument("--start", type=int, default=0)
    s.add_argument("--top", type=int, default=10)
    s.set_defaults(func=cmd_scan)

    r = sub.add_parser("replay", help="stream a generated match in scaled real time")
    r.add_argument("path")
    r.add_argument("--speed", type=float, default=20.0, help="time multiplier; 0 = no delay")
    r.add_argument("--compact", action="store_true", help="human-readable lines instead of JSON")
    r.set_defaults(func=cmd_replay)

    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
