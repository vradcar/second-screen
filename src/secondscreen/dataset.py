"""A synthetic season as an analytics dataset, for Microsoft Fabric (or any lakehouse).

Eight invented clubs play a double round-robin. Every match runs through the same
simulator and stats engine as the live demo, and the hidden story arcs come along
as ground-truth labels, so the dataset can answer questions a real feed can't:
how often does the engine catch a pressing spell, and how late?

Tables (Parquet):
    clubs, players, matches, standings     the league
    events                                  every on-ball event (about 2,800 per match)
    signals                                 what the stats engine raised, with evidence ids
    arcs                                    hidden story arcs (ground truth) and whether they were detected
    player_match                            per-player match stats incl. xG, distance, top speed

    python -m secondscreen.dataset --out data/season                       # local Parquet
    python -m secondscreen.dataset --onelake "<workspace>/<lakehouse>"      # + Fabric OneLake
    python -m secondscreen.dataset --adls "<storage account>/<container>"  # + Azure Data Lake

Uploads sign in with your Azure login (az login). In Fabric, run fabric/load_season.py
in a notebook to turn the files into Delta tables.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

from secondscreen.metrics import expected_goals
from secondscreen.simulator.engine import MatchSimulator
from secondscreen.simulator.teams import build_club
from secondscreen.stats.engine import StatsEngine
from secondscreen.stats.evaluate import ARC_TO_SIGNAL, match_arc

SEASON = "2026"
# (team_id, name, short, colours, style, quality, squad seed). The first two are the demo clubs.
LEAGUE = [
    ("HAL", "Halcyon City", "Halcyon", ("#1F4E8C", "#F2C14E"), {"directness": 0.22, "block": "mid_block", "tempo": 1.0}, 2, 1001),
    ("RED", "Redmarsh Rovers", "Redmarsh", ("#B3261E", "#F5F5F5"), {"directness": 0.48, "block": "high_press", "tempo": 1.1}, 0, 2002),
    ("SAL", "Saltmere United", "Saltmere", ("#0F7B6C", "#FFFFFF"), {"directness": 0.35, "block": "low_block", "tempo": 0.95}, 1, 3003),
    ("KES", "Kestrelford", "Kestrelford", ("#5B2A86", "#E9D8FD"), {"directness": 0.28, "block": "high_press", "tempo": 1.05}, 1, 4004),
    ("BRA", "Brackenmoor Athletic", "Brackenmoor", ("#2F6B2F", "#F4E04D"), {"directness": 0.55, "block": "mid_block", "tempo": 1.0}, -1, 5005),
    ("PAL", "Port Allard", "Port Allard", ("#0B3C5D", "#F28C28"), {"directness": 0.40, "block": "low_block", "tempo": 0.9}, 0, 6006),
    ("WYV", "Wyvern Hollow", "Wyvern", ("#7A1F1F", "#111111"), {"directness": 0.30, "block": "mid_block", "tempo": 1.08}, -1, 7007),
    ("LAR", "Larkspur Town", "Larkspur", ("#3A7BD5", "#FFFFFF"), {"directness": 0.45, "block": "high_press", "tempo": 1.12}, -2, 8008),
]
EVENT_COLS = ["event_id", "match_id", "seq", "period", "clock", "clock_seconds", "elapsed_seconds", "type", "team_id",
              "player_id", "player_name", "x", "y", "end_x", "end_y", "outcome", "recipient_id", "recipient_name",
              "distance_m", "ball_speed_kmh", "under_pressure", "progressive_m", "height", "shot_speed_kmh",
              "body_part", "situation", "card", "possession_id"]


def clubs() -> dict:
    """Fresh squads (a match mutates its clubs), identical every time."""
    taken: set[str] = set()
    out = {t: build_club(t, n, s, c, st, quality=q, seed=sd, taken=taken) for t, n, s, c, st, q, sd in LEAGUE[:2]}
    # The demo clubs keep their exact squads; the rest only need distinct full names.
    full = {p.name for c in out.values() for p in c.players}
    for t, n, s, c, st, q, sd in LEAGUE[2:]:
        out[t] = build_club(t, n, s, c, st, quality=q, seed=sd, taken=full, unique_full_names=True)
    return out


def fixtures() -> list[tuple[int, str, str]]:
    """Double round-robin by the circle method: (matchday, home, away)."""
    ids = [row[0] for row in LEAGUE]
    n, rounds = len(ids), []
    rot = ids[1:]
    for r in range(n - 1):
        order = [ids[0]] + rot
        pairs = [(order[i], order[n - 1 - i]) for i in range(n // 2)]
        rounds.append([(a, b) if (r + i) % 2 == 0 else (b, a) for i, (a, b) in enumerate(pairs)])
        rot = rot[-1:] + rot[:-1]
    out = [(md + 1, h, a) for md, rnd in enumerate(rounds) for h, a in rnd]
    out += [(md + n - 1, a, h) for md, h, a in out]            # second half of the season: reverse fixtures
    return out


def build(limit: int | None = None) -> dict[str, list[dict]]:
    t: dict[str, list[dict]] = defaultdict(list)
    for c in clubs().values():
        t["clubs"].append({"team_id": c.team_id, "name": c.name, "short_name": c.short_name, "primary_color": c.colors[0],
                           "secondary_color": c.colors[1], "block": c.style["block"], "directness": c.style["directness"],
                           "tempo": c.style["tempo"]})
        for p in c.players:
            t["players"].append({"player_id": p.player_id, "team_id": c.team_id, "name": p.name, "number": p.number,
                                 "position": p.position, "starter": p.on_pitch,
                                 **{k: v for k, v in p.public().items() if isinstance(v, int) and k != "number"}})
    for k, (md, home, away) in enumerate(fixtures()[:limit]):
        squads = clubs()
        match_id = f"S{SEASON[-2:]}M{k + 1:03d}"
        events, truth = MatchSimulator(squads[home], squads[away], seed=26000 + k, match_id=match_id).run()
        eng, signals = StatsEngine(), []
        for ev in events:
            signals += eng.ingest(ev)
        _match_rows(t, md, home, away, events, truth, signals, eng)
    t["standings"] = standings(t["matches"])
    return t


def _match_rows(t, md, home, away, events, truth, signals, eng) -> None:
    mid = events[0]["match_id"]
    xg = defaultdict(float)
    per = defaultdict(lambda: defaultdict(float))
    names: dict[str, tuple[str, str]] = {}
    for e in events:
        row = {c: e.get(c) for c in EVENT_COLS}
        row["xg"] = None
        if e["type"] == "shot":
            row["xg"] = round(expected_goals(e["x"], e["y"], e.get("body_part", "foot"), e.get("situation", "open_play")), 4)
            xg[e["team_id"]] += row["xg"]
        sc = e.get("score") or {}
        row["score_home"], row["score_away"] = sc.get(home), sc.get(away)
        extra = {k: v for k, v in e.items() if k not in EVENT_COLS and k not in ("score", "home", "away", "venue",
                                                                              "competition", "pitch", "players")}
        row["extra"] = json.dumps(extra) if extra else None
        t["events"].append(row)
        pid = e.get("player_id")
        if pid and e["type"] != "physical_snapshot":
            names[pid] = (e.get("player_name", ""), e["team_id"])
            s = per[pid]
            s["touches"] += 1
            if e["type"] == "pass":
                s["passes"] += 1
                s["passes_completed"] += e.get("outcome") == "complete"
                s["progressive_m"] += max(e.get("progressive_m") or 0, 0)
            elif e["type"] == "shot":
                s["shots"] += 1
                s["xg"] += row["xg"]
            elif e["type"] == "goal":
                s["goals"] += 1
            elif e["type"] in ("tackle", "interception", "pressure", "dribble", "save"):
                s[e["type"] + "s"] += 1
        if e["type"] == "physical_snapshot":
            for p in e.get("players", []):
                per[p["player_id"]]["distance_m"] = p["distance_m"]
                per[p["player_id"]]["top_speed_kmh"] = max(per[p["player_id"]]["top_speed_kmh"], p["top_speed_kmh"])
    for pid, s in per.items():
        if pid in names:
            t["player_match"].append({"match_id": mid, "player_id": pid, "player_name": names[pid][0],
                                      "team_id": names[pid][1], **{k: round(v, 3) for k, v in s.items()}})
    for s in signals:
        d = s.to_dict()
        t["signals"].append({"signal_id": d["signal_id"], "match_id": mid, "kind": d["kind"], "status": d["status"],
                             "period": d["period"], "clock": d["clock"], "minute": d["minute"], "elapsed": d["elapsed"],
                             "importance": d["importance"], "team_id": d.get("team_id"), "player_id": d.get("player_id"),
                             "facts": json.dumps(d["facts"]), "evidence": json.dumps(d["evidence"])})
    for i, a in enumerate(truth["arcs"]):
        hits = [s for s in signals if s.kind == ARC_TO_SIGNAL.get(a["kind"]) and match_arc(a, s)]
        first = min((s.minute for s in hits), default=None)
        t["arcs"].append({"arc_id": f"{mid}-A{i + 1}", "match_id": mid, "kind": a["kind"], "team_id": a["team_id"],
                          "player_id": a.get("player_id"), "start_min": a["start_min"], "end_min": a["end_min"],
                          "description": a["description"], "detected": bool(hits),
                          "first_detection_min": first,
                          "detection_lag_min": round(first - a["start_min"], 1) if first is not None else None})
    fs = truth["final_score"]
    t["matches"].append({"match_id": mid, "season": SEASON, "matchday": md, "home_id": home, "away_id": away,
                         "home_goals": fs[home], "away_goals": fs[away], "home_xg": round(xg[home], 3),
                         "away_xg": round(xg[away], 3), "events": len(events), "signals": len(signals),
                         "arcs": len(truth["arcs"]), "red_cards": sum(c["card"] == "second_yellow" for c in truth["cards"]),
                         "seed": truth["seed"]})


def standings(matches: list[dict]) -> list[dict]:
    tab = {r[0]: {"team_id": r[0], "name": r[1], "played": 0, "won": 0, "drawn": 0, "lost": 0, "gf": 0, "ga": 0,
                  "xg_for": 0.0, "xg_against": 0.0} for r in LEAGUE}
    for m in matches:
        for side, other in (("home", "away"), ("away", "home")):
            r = tab[m[f"{side}_id"]]
            gf, ga = m[f"{side}_goals"], m[f"{other}_goals"]
            r["played"] += 1
            r["gf"] += gf
            r["ga"] += ga
            r["xg_for"] = round(r["xg_for"] + m[f"{side}_xg"], 2)
            r["xg_against"] = round(r["xg_against"] + m[f"{other}_xg"], 2)
            r["won" if gf > ga else "drawn" if gf == ga else "lost"] += 1
    rows = [r | {"gd": r["gf"] - r["ga"], "points": 3 * r["won"] + r["drawn"]} for r in tab.values()]
    rows.sort(key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["name"]))
    return [r | {"position": i + 1} for i, r in enumerate(rows)]


def write_parquet(tables: dict[str, list[dict]], out: Path) -> list[Path]:
    import pyarrow as pa
    import pyarrow.parquet as pq
    out.mkdir(parents=True, exist_ok=True)
    paths = []
    for name, rows in tables.items():
        p = out / f"{name}.parquet"
        pq.write_table(pa.Table.from_pylist(rows), p, compression="zstd")
        paths.append(p)
    return paths


def upload(paths: list[Path], target: str, onelake: bool) -> str:
    from azure.identity import DefaultAzureCredential
    from azure.storage.filedatalake import DataLakeServiceClient
    first, _, rest = target.partition("/")
    if onelake:     # workspace / lakehouse
        svc = DataLakeServiceClient("https://onelake.dfs.fabric.microsoft.com", credential=DefaultAzureCredential())
        fs, base = svc.get_file_system_client(first), f"{rest.removesuffix('.Lakehouse')}.Lakehouse/Files/second-screen/season_{SEASON}"
    else:           # storage account / container
        svc = DataLakeServiceClient(f"https://{first}.dfs.core.windows.net", credential=DefaultAzureCredential())
        fs, base = svc.get_file_system_client(rest), f"second-screen/season_{SEASON}"
    for p in paths:
        with p.open("rb") as f:
            fs.get_file_client(f"{base}/{p.name}").upload_data(f, overwrite=True)
        print(f"  uploaded {base}/{p.name}")
    return base


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.dataset")
    ap.add_argument("--out", default="data/season")
    ap.add_argument("--matches", type=int, help="only the first N fixtures (default: the whole season)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--onelake", metavar="WORKSPACE/LAKEHOUSE", help="upload to a Fabric lakehouse")
    g.add_argument("--adls", metavar="ACCOUNT/CONTAINER", help="upload to Azure Data Lake Storage")
    args = ap.parse_args()
    tables = build(args.matches)
    paths = write_parquet(tables, Path(args.out))
    for name, rows in tables.items():
        print(f"{name:13s} {len(rows):>8,} rows")
    arcs = tables["arcs"]
    by = defaultdict(list)
    for a in arcs:
        by[a["kind"]].append(a["detected"])
    print("detector recall:", ", ".join(f"{k} {sum(v) / len(v):.2f}" for k, v in sorted(by.items())))
    top = tables["standings"][0]
    print(f"champions: {top['name']} ({top['points']} pts)")
    if args.onelake or args.adls:
        upload(paths, args.onelake or args.adls, bool(args.onelake))


if __name__ == "__main__":
    main()
