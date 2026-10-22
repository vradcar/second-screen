"""The analyst's view of a match up to a given moment: what a club's analysis team watches live.

    team comparison   possession, xG, shots, big chances, passing, progression, box entries, field
                      tilt, pressing (PPDA), high turnovers, corners, fouls, cards
    players           minutes, touches, passing, progression, chance creation, shooting, duels,
                      pressing, discipline, distance and top speed, for every player in the squad
    shots             every shot with location, chance quality (xG), outcome, body part, situation
    xg_flow           cumulative xG per team over time, with the goals
    pass_networks     average positions and the most-used passing links, per team
    heatmaps          touch grids (5 m cells) per player
    key_events        goals, cards and substitutions

Coordinates are normalised so every team attacks left to right (x 0-105, y 0-68).
Everything is computed from the event feed with the same stats engine as the live pipeline.
"""
from __future__ import annotations

from collections import Counter, defaultdict

from secondscreen import metrics
from secondscreen.stats.engine import StatsEngine

CELL = 5.0
TOUCH_TYPES = {"pass", "carry", "dribble", "shot", "tackle", "interception", "clearance", "save", "block", "pressure"}


def analyse(events: list[dict], upto: float | None = None) -> dict:
    eng = StatsEngine()
    seen: list[dict] = []
    for ev in events:
        if upto is not None and ev["elapsed_seconds"] > upto:
            break
        eng.ingest(ev)
        seen.append(ev)
    if not eng.home:
        return {"ready": False}
    home, away = eng.home, eng.away
    start = seen[0]

    def rel(team: str, x: float | None, y: float | None) -> tuple[float, float]:
        if x is None or y is None:
            return (0.0, 0.0)
        return (round(eng.ax(team, x), 1), round(y if team == home else metrics.PITCH_Y - y, 1))

    # ---------------------------------------------------------------- minutes on the pitch
    now_clock = seen[-1]["clock_seconds"]
    on_at: dict[str, float] = {}
    off_at: dict[str, float] = {}
    for side in ("home", "away"):
        for p in start[side]["starting_xi"]:
            on_at[p["player_id"]] = 0.0
    shots, xg_flow = [], {home: [[0, 0.0]], away: [[0, 0.0]]}
    cum = {home: 0.0, away: 0.0}
    links: dict[str, Counter] = {home: Counter(), away: Counter()}
    spots: dict[str, list[tuple[float, float]]] = defaultdict(list)
    heat: dict[str, Counter] = defaultdict(Counter)
    for ev in seen:
        t, team, pid = ev["type"], ev.get("team_id"), ev.get("player_id")
        if t == "substitution":
            on_at[pid] = ev["clock_seconds"]
            off_at[ev["player_off_id"]] = ev["clock_seconds"]
        elif t == "card" and ev.get("card") != "yellow":
            off_at[pid] = ev["clock_seconds"]
        if t == "shot":
            x, y = rel(team, ev["x"], ev["y"])
            xg = metrics.expected_goals(x, y, ev.get("body_part", "foot"), ev.get("situation", "open_play"))
            cum[team] += xg
            shots.append({"team_id": team, "player_id": pid, "player": ev.get("player_name"), "clock": ev["clock"],
                          "minute": int(ev["clock_seconds"] // 60) + 1, "x": x, "y": y, "xg": round(xg, 2),
                          "outcome": ev.get("outcome"), "body_part": ev.get("body_part"),
                          "situation": ev.get("situation"), "speed_kmh": ev.get("shot_speed_kmh")})
            xg_flow[team].append([round(ev["elapsed_seconds"]), round(cum[team], 2)])
        if t == "pass" and ev.get("outcome") == "complete" and ev.get("recipient_id"):
            links[team][(pid, ev["recipient_id"])] += 1
            spots[pid].append(rel(team, ev["x"], ev["y"]))
            spots[ev["recipient_id"]].append(rel(team, ev.get("end_x"), ev.get("end_y")))
        if t in TOUCH_TYPES and pid and ev.get("x") is not None:
            x, y = rel(team, ev["x"], ev["y"])
            heat[pid][(min(int(x // CELL), 20), min(int(y // CELL), 13))] += 1

    end_elapsed = round(seen[-1]["elapsed_seconds"])
    for tm in (home, away):
        xg_flow[tm].append([end_elapsed, round(cum[tm], 2)])

    # ---------------------------------------------------------------- players
    lineup = {p["player_id"]: (side, p, i < 11) for side in ("home", "away")
              for i, p in enumerate(start[side]["starting_xi"] + start[side]["bench"])}
    players = []
    for pid, (side, info, starter) in lineup.items():
        ps = eng.player(pid)
        mins = 0
        if pid in on_at:
            mins = round((off_at.get(pid, now_clock) - on_at[pid]) / 60)
        players.append({
            "player_id": pid, "name": info["name"], "number": info["number"], "position": info["position"],
            "team_id": start[side]["team_id"], "starter": starter, "on_pitch": ps.on_pitch if ps else starter,
            "minutes": max(mins, 0), "touches": ps.touches, "passes": ps.passes, "passes_completed": ps.passes_completed,
            "pass_completion": ps.pass_completion, "progressive_passes": ps.progressive_passes,
            "key_passes": ps.key_passes, "shots": ps.shots, "shots_on_target": ps.shots_on_target,
            "xg": round(ps.xg, 2), "goals": ps.goals, "assists": ps.assists, "dribbles": ps.dribbles,
            "tackles_won": ps.tackles_won, "interceptions": ps.interceptions, "pressures": ps.pressures,
            "fouls": ps.fouls, "yellow_cards": ps.yellow_cards, "red_card": ps.red_card,
            "distance_km": round(ps.distance_m / 1000, 1), "top_speed_kmh": round(ps.top_speed_kmh, 1),
        })

    # ---------------------------------------------------------------- pass networks
    networks = {}
    for tm in (home, away):
        counts = Counter()
        for (a, b), n in links[tm].items():
            counts[a] += n
        nodes = []
        for p in players:
            if p["team_id"] == tm and spots.get(p["player_id"]) and counts[p["player_id"]] + len(spots[p["player_id"]]) >= 6:
                xs, ys = zip(*spots[p["player_id"]])
                nodes.append({"player_id": p["player_id"], "name": p["name"], "number": p["number"],
                              "x": round(sum(xs) / len(xs), 1), "y": round(sum(ys) / len(ys), 1),
                              "passes": counts[p["player_id"]]})
        ids = {n["player_id"] for n in nodes}
        pair = Counter()
        for (a, b), n in links[tm].items():
            if a in ids and b in ids:
                pair[tuple(sorted((a, b)))] += n
        edges = [{"a": a, "b": b, "count": n} for (a, b), n in pair.most_common() if n >= 3]
        networks[tm] = {"nodes": nodes, "edges": edges}

    teams = eng.team_summary()
    return {
        "ready": True, "match_id": eng.match_id, "clock": eng.clock, "elapsed": end_elapsed, "home": home, "away": away,
        "formations": {start["home"]["team_id"]: start["home"].get("formation", "4-3-3"),
                       start["away"]["team_id"]: start["away"].get("formation", "4-3-3")},
        "teams": teams, "players": players, "shots": shots, "xg_flow": xg_flow, "pass_networks": networks,
        "heatmaps": {pid: [[i, j, n] for (i, j), n in grid.items()] for pid, grid in heat.items()},
        "key_events": eng.key_events,
    }
