"""Incremental stats engine: raw events in, statistics and evidence-linked signals out.

Everything here is deterministic code. No LLM touches a number.

    engine = StatsEngine()
    for event in stream:
        for signal in engine.ingest(event):
            ...                 # hand to the agent layer
    engine.snapshot()           # full state for the UI / agents
"""
from __future__ import annotations

import math
from bisect import bisect_left
from collections import deque
from typing import NamedTuple

from secondscreen import metrics
from secondscreen.stats.signals import THRESHOLDS as T
from secondscreen.stats.signals import Signal
from secondscreen.stats.state import PlayerStats, TeamStats

TICK = 60.0              # detectors run once per match minute
MOMENTUM_TAU = 180.0     # threat decays with a 3-minute time constant
MOMENTUM_SCALE = 3.5     # threat difference that maps to ~76 on the momentum scale
PRESS_PRIOR = 4.0
HOT_PRIOR = 4.0          # pseudo-count for touch-share ratios
DECISIVE = ("shot", "key_pass", "dribble", "goal", "assist")        # pseudo-count shrinking pressing ratios toward 1


class Rec(NamedTuple):
    """Compact log record used for rolling windows."""
    t: float
    team: str
    player: str | None
    kind: str
    value: float
    eid: str


class StatsEngine:
    def __init__(self) -> None:
        self.match_id: str | None = None
        self.home: str | None = None
        self.away: str | None = None
        self.teams: dict[str, TeamStats] = {}
        self.score: dict[str, int] = {}
        self.period, self.clock, self.minute, self.elapsed = 1, "00:00", 0.0, 0.0

        self.log: list[Rec] = []
        self.log_t: list[float] = []
        self.spells: list[list] = []          # [team, start, end, passes]
        self.cur_poss: list | None = None
        self.poss_events: deque[str] = deque(maxlen=12)
        self.last_completed: tuple[int, str, str, str] | None = None  # (poss_id, passer, recipient, eid)
        self.last_shot: dict | None = None
        self.max_deficit: dict[str, int] = {}

        self.signals: list[Signal] = []
        self.key_events: list[dict] = []     # goals, cards, subs: the match sheet
        self._new: list[Signal] = []
        self.next_tick = TICK
        self.momentum = 0.0
        self.regime = "balanced"
        self._regime_pending: tuple[str, int] = ("balanced", 0)
        self.series: list[dict] = []          # per-minute timeline for charts

        self._press = {}                      # team -> detector state
        self._fade_ref: dict[str, float] = {}
        self._fade_count: dict[str, int] = {}
        self._fired: set[tuple] = set()
        self._hot_until: dict[str, float] = {}
        self._mom_ref: list[tuple[float, float]] = []
        self._cooldown: dict[str, float] = {}
        self._regime_since = 0.0

    # ------------------------------------------------------------ utilities
    def ax(self, team: str, x: float) -> float:
        """Absolute x → attacking-frame x for `team`."""
        return x if team == self.home else metrics.PITCH_X - x

    def opp(self, team: str) -> str:
        return self.away if team == self.home else self.home

    def player(self, pid: str | None) -> PlayerStats | None:
        if not pid:
            return None
        return self.teams[pid.split("-")[0]].players.get(pid)

    def rec(self, ev: dict, kind: str, value: float = 1.0, team: str | None = None, player: str | None = None):
        self.log.append(Rec(self.elapsed, team or ev.get("team_id"), player or ev.get("player_id"),
                            kind, value, ev["event_id"]))
        self.log_t.append(self.elapsed)

    def window(self, secs: float) -> list[Rec]:
        return self.log[bisect_left(self.log_t, self.elapsed - secs):]

    def poss_seconds(self, team: str, secs: float) -> float:
        lo = self.elapsed - secs
        total = 0.0
        spells = self.spells + ([self.cur_poss] if self.cur_poss else [])
        for tm, s, e, _ in reversed(spells):
            e = self.elapsed if e is None else e
            if e < lo:
                break
            if tm == team:
                total += max(0.0, min(e, self.elapsed) - max(s, lo))
        return total

    def emit(self, kind: str, importance: float, team: str | None = None, player: str | None = None,
             status: str = "instant", facts: dict | None = None, evidence: list[str] | None = None) -> Signal:
        sig = Signal(
            signal_id=f"{self.match_id}-S{len(self.signals) + 1:04d}", kind=kind, period=self.period,
            clock=self.clock, minute=round(self.minute, 1), elapsed=round(self.elapsed, 1),
            importance=importance, team_id=team, player_id=player, status=status,
            facts=facts or {}, evidence=evidence or [],
        )
        self.signals.append(sig)
        self._new.append(sig)
        return sig

    def _name(self, pid: str | None) -> str | None:
        p = self.player(pid)
        return p.name if p else None

    # --------------------------------------------------------------- ingest
    def ingest(self, ev: dict) -> list[Signal]:
        self._new = []
        self.period = ev["period"]
        self.clock = ev["clock"]
        self.minute = ev["clock_seconds"] / 60.0
        self.elapsed = ev["elapsed_seconds"]
        while self.elapsed >= self.next_tick and self.home:
            self.tick()
            self.next_tick += TICK
        handler = getattr(self, f"on_{ev['type']}", None)
        if handler:
            handler(ev)
        if ev.get("possession_id") is not None and ev["type"] not in ("physical_snapshot",):
            self.poss_events.append(ev["event_id"])
        return self._new

    def on_match_start(self, ev: dict) -> None:
        self.match_id = ev["match_id"]
        for side in ("home", "away"):
            info = ev[side]
            ts = TeamStats(info["team_id"], info["name"])
            for grp, on in (("starting_xi", True), ("bench", False)):
                for p in info[grp]:
                    ts.players[p["player_id"]] = PlayerStats(p["player_id"], p["name"], info["team_id"],
                                                             p["position"], p["number"], on_pitch=on)
            self.teams[info["team_id"]] = ts
        self.home, self.away = ev["home"]["team_id"], ev["away"]["team_id"]
        self.score = {self.home: 0, self.away: 0}
        self.max_deficit = {self.home: 0, self.away: 0}
        for tm in self.teams:
            self._press[tm] = {"active": False, "streak": 0, "off_streak": 0, "history": [], "start": None}

    def on_possession_start(self, ev: dict) -> None:
        team = ev["team_id"]
        if self.cur_poss and self.cur_poss[0] == team:
            return
        if self.cur_poss:
            self.cur_poss[2] = self.elapsed
            self.teams[self.cur_poss[0]].possession_seconds += self.elapsed - self.cur_poss[1]
            self.spells.append(self.cur_poss)
        self.cur_poss = [team, self.elapsed, None, 0]
        self.poss_events.clear()

    def on_possession_change(self, ev: dict) -> None:
        self.rec(ev, "pchange")

    def on_pass(self, ev: dict) -> None:
        team = ev["team_id"]
        ts = self.teams[team]
        p = self.player(ev["player_id"])
        sx, ex = self.ax(team, ev["x"]), self.ax(team, ev["end_x"])
        end_in_box = metrics.in_box(ex, ev["end_y"])
        progressive = ex - sx  # computed from coordinates rather than trusting the feed
        pressured = bool(ev.get("under_pressure"))
        diff = metrics.pass_difficulty(ev["distance_m"], pressured, progressive, end_in_box)
        complete = ev["outcome"] == "complete"
        ts.passes += 1
        ts.pass_difficulty_sum += diff
        p.passes += 1
        p.touches += 1
        if sx < 63:
            self.teams[self.opp(team)].ppda_opp_passes += 1
        self.rec(ev, "pass", 1.0 if complete else 0.0)
        self.rec(ev, "touch")
        if self.cur_poss and self.cur_poss[0] == team:
            self.cur_poss[3] += 1
        if not complete:
            return
        ts.passes_completed += 1
        p.passes_completed += 1
        self.last_completed = (ev["possession_id"], ev["player_id"], ev["recipient_id"], ev["event_id"])
        if sx > 70:
            ts.final_third_passes += 1
            self.rec(ev, "threat", 0.15)
            self.rec(ev, "f3")
        if progressive >= 10:
            ts.progressive_passes += 1
            p.progressive_passes += 1
        entry = end_in_box and not metrics.in_box(sx, ev["y"])
        if entry:
            ts.box_entries += 1
            self.rec(ev, "threat", 0.6)
            self.rec(ev, "box_entry")
        if diff >= T["elite_pass_difficulty"] and (progressive >= 15 or entry):
            p.elite_passes += 1
            self.emit("elite_pass", 0.25, team, ev["player_id"], facts={
                "player": p.name, "recipient": ev.get("recipient_name"), "difficulty": diff,
                "distance_m": ev["distance_m"], "progressive_m": round(progressive, 1),
                "under_pressure": pressured, "into_box": entry,
            }, evidence=[ev["event_id"]])

    def on_pressure(self, ev: dict) -> None:
        team = ev["team_id"]
        self.teams[team].pressures += 1
        self.player(ev["player_id"]).pressures += 1
        if self.ax(team, ev["x"]) > 52.5:
            self.rec(ev, "press_high")

    def _def_action(self, ev: dict) -> None:
        team = ev["team_id"]
        x = self.ax(team, ev["x"])
        if x > 42:
            self.teams[team].ppda_def_actions += 1
        if x > 52.5:
            self.rec(ev, "press_high")
        if x > 65:
            self.teams[team].high_turnovers += 1
            self.rec(ev, "threat", 0.4)
            self.rec(ev, "high_turnover")

    def on_tackle(self, ev: dict) -> None:
        if ev["outcome"] != "won":
            return
        self.teams[ev["team_id"]].tackles_won += 1
        self.player(ev["player_id"]).tackles_won += 1
        self._def_action(ev)

    def on_interception(self, ev: dict) -> None:
        self.teams[ev["team_id"]].interceptions += 1
        self.player(ev["player_id"]).interceptions += 1
        self._def_action(ev)

    def on_foul(self, ev: dict) -> None:
        self.teams[ev["team_id"]].fouls += 1
        self.player(ev["player_id"]).fouls += 1
        if self.ax(ev["team_id"], ev["x"]) > 42:
            self.teams[ev["team_id"]].ppda_def_actions += 1

    def _key(self, ev: dict, kind: str, **extra) -> None:
        self.key_events.append({"kind": kind, "team_id": ev.get("team_id"), "player_id": ev.get("player_id"),
                                "player": ev.get("player_name"), "clock": ev["clock"], "elapsed": ev["elapsed_seconds"],
                                **extra})

    def on_card(self, ev: dict) -> None:
        ts = self.teams[ev["team_id"]]
        p = self.player(ev["player_id"])
        self._key(ev, "yellow" if ev["card"] == "yellow" else "red")
        if ev["card"] == "yellow":
            ts.yellow_cards += 1
            p.yellow_cards += 1
            self.emit("yellow_card", 0.2, ev["team_id"], p.player_id, facts={"player": p.name},
                      evidence=[ev["event_id"]])
            return
        ts.red_cards += 1
        ts.yellow_cards += 1
        p.yellow_cards += 1
        p.red_card, p.on_pitch = True, False
        ts.players_on_pitch -= 1
        self.emit("red_card", 0.85, ev["team_id"], p.player_id, facts={
            "player": p.name, "reason": "second yellow", "players_left": ts.players_on_pitch,
            "score": dict(self.score),
        }, evidence=[ev["event_id"]])

    def on_carry(self, ev: dict) -> None:
        p = self.player(ev["player_id"])
        p.touches += 1
        self.rec(ev, "touch")
        speed = ev.get("speed_kmh", 0.0)
        prev = p.top_speed_kmh
        p.top_speed_kmh = max(p.top_speed_kmh, speed)
        if speed >= T["speed_alert_kmh"] and prev < T["speed_alert_kmh"]:
            match_top = max(pl.top_speed_kmh for t in self.teams.values() for pl in t.players.values())
            self.emit("speed_alert", 0.3 + (0.1 if speed >= match_top else 0), ev["team_id"], p.player_id, facts={
                "player": p.name, "speed_kmh": speed, "carry_distance_m": ev.get("distance_m"),
                "match_top_speed": speed >= match_top,
            }, evidence=[ev["event_id"]])

    def on_dribble(self, ev: dict) -> None:
        self.player(ev["player_id"]).dribbles += 1
        self.rec(ev, "dribble")
        self.rec(ev, "threat", 0.1)

    def on_shot(self, ev: dict) -> None:
        team = ev["team_id"]
        ts = self.teams[team]
        p = self.player(ev["player_id"])
        x = self.ax(team, ev["x"])
        y = ev["y"] if team == self.home else metrics.PITCH_Y - ev["y"]
        xg = metrics.expected_goals(x, y, ev.get("body_part", "foot"), ev.get("situation", "open_play"))
        dist, _ = metrics.shot_geometry(x, y)
        on_target = ev["outcome"] in ("goal", "saved")
        ts.shots += 1
        ts.xg += xg
        p.shots += 1
        p.touches += 1
        p.xg += xg
        p.max_shot_speed_kmh = max(p.max_shot_speed_kmh, ev.get("shot_speed_kmh", 0.0))
        if on_target:
            ts.shots_on_target += 1
            p.shots_on_target += 1
        self.rec(ev, "shot", xg)
        self.rec(ev, "touch")
        self.rec(ev, "threat", xg * 3)
        key_passer = None
        if self.last_completed and self.last_completed[0] == ev["possession_id"] and self.last_completed[2] == p.player_id:
            key_passer = self.last_completed[1]
            self.player(key_passer).key_passes += 1
            self.rec(ev, "key_pass", player=key_passer)
        self.last_shot = {"event_id": ev["event_id"], "xg": xg, "player": p.name, "player_id": p.player_id,
                          "distance_m": round(dist, 1), "outcome": ev["outcome"],
                          "key_passer": self._name(key_passer), "speed_kmh": ev.get("shot_speed_kmh"),
                          "situation": ev.get("situation"), "body_part": ev.get("body_part")}
        if xg >= T["big_chance_xg"]:
            ts.big_chances += 1
            if ev["outcome"] != "goal":
                kind = "big_save" if ev["outcome"] == "saved" else "big_chance_missed"
                self.emit(kind, 0.6, team, p.player_id, facts={**self.last_shot},
                          evidence=list(self.poss_events)[-6:] + [ev["event_id"]])
        if ev.get("shot_speed_kmh", 0) >= T["shot_speed_kmh"]:
            self.emit("shot_speed", 0.35, team, p.player_id, facts={
                "player": p.name, "shot_speed_kmh": ev["shot_speed_kmh"], "outcome": ev["outcome"],
                "distance_m": round(dist, 1)}, evidence=[ev["event_id"]])

    def on_goal(self, ev: dict) -> None:
        self._key(ev, "goal", assist=ev.get("assist_name"))
        team, other = ev["team_id"], self.opp(ev["team_id"])
        before_us, before_them = self.score[team], self.score[other]
        self.score = dict(ev["score"])
        ts = self.teams[team]
        ts.goals += 1
        scorer = self.player(ev["player_id"])
        scorer.goals += 1
        if ev.get("assist_player_id"):
            self.player(ev["assist_player_id"]).assists += 1
            self.rec(ev, "assist", player=ev["assist_player_id"])
        self.rec(ev, "goal")
        us, them = self.score[team], self.score[other]
        if before_us < before_them:
            state = "equaliser" if us == them else "pulls_one_back"
        elif before_us == before_them:
            state = "opener" if before_us == 0 else "go_ahead"
        else:
            state = "extends_lead"
        comeback = state == "go_ahead" and self.max_deficit[team] >= 1
        self.max_deficit[other] = max(self.max_deficit[other], us - them)
        late = self.period == 2 and self.minute >= 80
        importance = 1.0 if state in ("equaliser", "go_ahead", "opener") or late else 0.9
        facts = {
            "scorer": scorer.name, "assist": ev.get("assist_name"), "game_state": state,
            "comeback_complete": comeback, "max_deficit_overcome": self.max_deficit[team] if comeback else 0,
            "score": dict(self.score), "scorer_goals_today": scorer.goals,
            "shot": self.last_shot, "team_xg": round(ts.xg, 2), "opp_xg": round(self.teams[other].xg, 2),
            "possession_passes": self.cur_poss[3] if self.cur_poss and self.cur_poss[0] == team else 0,
            "players_on_pitch": {team: ts.players_on_pitch, other: self.teams[other].players_on_pitch},
        }
        self.emit("goal", importance, team, scorer.player_id, facts=facts,
                  evidence=list(self.poss_events)[-8:] + [ev["event_id"]])

    def on_save(self, ev: dict) -> None:
        pass

    def on_corner(self, ev: dict) -> None:
        self.teams[ev["team_id"]].corners += 1
        self.rec(ev, "threat", 0.3)

    def on_penalty_awarded(self, ev: dict) -> None:
        self.emit("penalty_awarded", 0.8, ev["team_id"], ev["player_id"], facts={
            "taker": ev["player_name"], "score": dict(self.score)},
            evidence=list(self.poss_events)[-4:] + [ev["event_id"]])

    def on_substitution(self, ev: dict) -> None:
        on, off = self.player(ev["player_id"]), self.player(ev["player_off_id"])
        self._key(ev, "sub", off_id=off.player_id, off=off.name)
        on.on_pitch, off.on_pitch = True, False
        self.emit("substitution", 0.2, ev["team_id"], on.player_id, facts={
            "on": on.name, "off": off.name, "off_distance_km": round(off.distance_m / 1000, 2)},
            evidence=[ev["event_id"]])

    def on_physical_snapshot(self, ev: dict) -> None:
        for row in ev["players"]:
            p = self.player(row["player_id"])
            prev = p.distance_m
            p.distance_m = row["distance_m"]
            p.top_speed_kmh = max(p.top_speed_kmh, row["top_speed_kmh"])
            for m in T["distance_milestones_m"]:
                if prev < m <= p.distance_m and m >= 10000:
                    self.emit("distance_milestone", 0.15 if m == 10000 else 0.3, p.team_id, p.player_id,
                              facts={"player": p.name, "distance_km": round(p.distance_m / 1000, 2),
                                     "milestone_km": m // 1000}, evidence=[ev["event_id"]])

    def on_period_end(self, ev: dict) -> None:
        self.tick()
        kind = "half_time" if ev["period"] == 1 else "full_time"
        self.emit(kind, 0.7, facts={"score": dict(self.score), "stats": self.team_summary()},
                  evidence=[ev["event_id"]])

    # ---------------------------------------------------------- per-minute
    def tick(self) -> None:
        """Rolling-window analysis, run once per match minute."""
        self._momentum()
        self._regime()
        for team in self.teams:
            self._pressing(team)
            self._fade(team)
            self._surge(team)
        self._hot_streaks()
        self.series.append({
            "minute": round(self.minute, 1), "period": self.period, "elapsed": round(self.elapsed),
            "momentum": round(self.momentum, 1), "regime": self.regime, "score": dict(self.score),
            "xg": {t: round(s.xg, 2) for t, s in self.teams.items()},
        })

    def _momentum(self) -> None:
        threat = {self.home: 0.0, self.away: 0.0}
        for r in self.window(600):
            if r.kind == "threat":
                threat[r.team] += r.value * math.exp(-(self.elapsed - r.t) / MOMENTUM_TAU)
        new = 100 * math.tanh((threat[self.home] - threat[self.away]) / MOMENTUM_SCALE)
        self._mom_ref.append((self.elapsed, new))
        self.momentum = new
        # A swing: momentum moved a long way in 5 minutes and now clearly favours the other side.
        old = next((m for t, m in reversed(self._mom_ref) if t <= self.elapsed - 300), None)
        if old is None or self.elapsed < self._cooldown.get("swing", 0):
            return
        if abs(new - old) >= T["momentum_swing"] and old * new < 0 and abs(new) >= 35:
            team = self.home if new > old else self.away
            self._cooldown["swing"] = self.elapsed + 600
            w = self.window(300)
            self.emit("momentum_swing", 0.55, team, facts={
                "momentum_before": round(old, 1), "momentum_now": round(new, 1),
                "shots_last_5": sum(1 for r in w if r.kind == "shot" and r.team == team),
                "box_entries_last_5": sum(1 for r in w if r.kind == "box_entry" and r.team == team),
                "opp_shots_last_5": sum(1 for r in w if r.kind == "shot" and r.team != team),
            }, evidence=[r.eid for r in w if r.team == team and r.kind in ("shot", "box_entry")][-6:])

    def _regime(self) -> None:
        """Classify the last 5 minutes as control (one side keeps the ball), chaos
        (the ball keeps changing hands) or balanced. Changes need 3 minutes of
        confirmation and the regime must have lasted 5 minutes before it can flip."""
        if self.elapsed < 300:
            return
        w = self.window(300)
        cpm = sum(1 for r in w if r.kind == "pchange") / 5
        share = {t: self.poss_seconds(t, 300) for t in self.teams}
        total = sum(share.values()) or 1.0
        leader = max(share, key=share.get)
        lead_share = share[leader] / total
        if cpm >= T["chaos_changes_per_min"]:
            regime = "chaos"
        elif lead_share >= T["control_share"]:
            regime = f"control:{leader}"
        else:
            regime = "balanced"
        pend, n = self._regime_pending
        self._regime_pending = (regime, n + 1) if regime == pend else (regime, 1)
        if (regime != self.regime and self._regime_pending[1] >= 3
                and self.elapsed - self._regime_since >= 300):
            prev, self.regime = self.regime, regime
            self._regime_since = self.elapsed
            passes = [r for r in w if r.kind == "pass"]
            self.emit("regime_change", 0.4, leader if regime.startswith("control") else None, facts={
                "from": prev, "to": regime, "possession_changes_per_min": round(cpm, 2),
                "possession_share_last_5": {t: round(s / total, 2) for t, s in share.items()},
                "pass_completion_last_5": round(sum(r.value for r in passes) / len(passes), 2) if passes else None,
            }, evidence=[r.eid for r in w if r.kind == "pchange"][-6:])

    def _pressing(self, team: str) -> None:
        """Pressing intensity = high defensive actions per minute of opponent possession,
        compared with the team's own running baseline. The ratio is shrunk toward 1
        with a pseudo-count, so sides that rarely press don't trigger on two tackles."""
        st = self._press[team]
        if self.elapsed < 360:
            return
        opp_min = max(self.poss_seconds(self.opp(team), 360) / 60, 1.0)
        w = self.window(360)
        acts = [r for r in w if r.team == team and r.kind == "press_high"]
        rate = len(acts) / opp_min
        hist = st["history"]
        st["rate"] = rate
        if len(hist) < 6:
            hist.append(rate)
            return
        baseline = sum(hist) / len(hist)
        expected = baseline * opp_min
        ratio = (len(acts) + PRESS_PRIOR) / (expected + PRESS_PRIOR)
        st["ratio"] = ratio
        if not st["active"]:
            hist.append(rate)
            if self.elapsed < st.get("cooldown", 0):
                return
            st["streak"] = st["streak"] + 1 if ratio >= T["press_ratio_on"] else 0
            if st["streak"] >= 3:
                opp = self.opp(team)
                chasing = self.period == 2 and self.minute >= 65 and self.score[team] < self.score[opp]
                st.update(active=True, off_streak=0, start=self.elapsed, start_min=self.minute, peak=ratio)
                opp_passes = [r for r in w if r.team == opp and r.kind == "pass"]
                self.emit("pressing_spell", 0.6, team, status="start", facts={
                    "press_actions_last_6": len(acts),
                    "press_actions_per_opp_poss_min": round(rate, 2), "baseline": round(baseline, 2),
                    "ratio": round(ratio, 2), "context": "chasing_the_game" if chasing else "tactical",
                    "high_turnovers_last_6": sum(1 for r in w if r.team == team and r.kind == "high_turnover"),
                    "opp_pass_completion_last_6": round(sum(r.value for r in opp_passes) / len(opp_passes), 2) if opp_passes else None,
                    "opp_pass_completion_match": self.teams[opp].pass_completion,
                }, evidence=[r.eid for r in acts][-8:])
        else:
            st["peak"] = max(st["peak"], ratio)
            st["off_streak"] = st["off_streak"] + 1 if ratio < T["press_ratio_off"] else 0
            if st["off_streak"] >= 2:
                st.update(active=False, streak=0, cooldown=self.elapsed + 480)
                self.emit("pressing_spell", 0.35, team, status="end", facts={
                    "started_minute": round(st["start_min"], 1),
                    "duration_min": round((self.elapsed - st["start"]) / 60, 1),
                    "peak_ratio": round(st["peak"], 2)})

    def _fade(self, team: str) -> None:
        if self.period != 2:
            return
        if team not in self._fade_ref and self.minute >= 55:
            ts = self.teams[team]
            self._fade_ref[team] = ts.pass_completion or 0.0
        if self.minute < 60 or ("fade", team) in self._fired:
            return
        w = [r for r in self.window(600) if r.team == team and r.kind == "pass"]
        if len(w) < 25:
            return
        recent = sum(r.value for r in w) / len(w)
        drop = self._fade_ref[team] - recent
        n = self._fade_count.get(team, 0)
        self._fade_count[team] = n + 1 if drop >= T["fade_completion_drop"] else 0
        if self._fade_count[team] >= 3:
            self._fired.add(("fade", team))
            on = [p for p in self.teams[team].players.values() if p.on_pitch and p.position != "GK"]
            self.emit("fatigue_fade", 0.5, team, status="start", facts={
                "pass_completion_before_55": round(self._fade_ref[team], 3),
                "pass_completion_last_10": round(recent, 3),
                "avg_outfield_distance_km": round(sum(p.distance_m for p in on) / len(on) / 1000, 2),
                "players_on_pitch": self.teams[team].players_on_pitch,
            }, evidence=[r.eid for r in w if r.value == 0][-6:])

    def _surge(self, team: str) -> None:
        if self.period != 2 or self.minute < 70 or ("surge", team) in self._fired:
            return
        if self.score[team] > self.score[self.opp(team)]:
            return
        w = self.window(480)
        threat = {t: sum(r.value for r in w if r.kind == "threat" and r.team == t) for t in self.teams}
        total = sum(threat.values())
        if total < 2.0:
            return
        share = threat[team] / total
        if share >= T["surge_threat_share"]:
            self._fired.add(("surge", team))
            self.emit("late_surge", 0.65, team, status="start", facts={
                "threat_share_last_8": round(share, 2),
                "shots_last_8": sum(1 for r in w if r.kind == "shot" and r.team == team),
                "opp_shots_last_8": sum(1 for r in w if r.kind == "shot" and r.team != team),
                "box_entries_last_8": sum(1 for r in w if r.kind == "box_entry" and r.team == team),
                "score": dict(self.score),
            }, evidence=[r.eid for r in w if r.team == team and r.kind in ("shot", "box_entry")][-8:])

    def _hot_streaks(self) -> None:
        """A player is on a hot streak when his share of the team's touches in the last
        12 minutes jumps well above his own earlier share, and he's doing something
        decisive with the ball (shots, key passes, dribbles). Shrunk with a pseudo-count."""
        if self.elapsed < 1200:
            return
        lo = bisect_left(self.log_t, self.elapsed - 720)
        prior, recent = self.log[:lo], self.log[lo:]
        for team in self.teams:
            prior_t = [r for r in prior if r.team == team and r.kind == "touch"]
            recent_t = [r for r in recent if r.team == team and r.kind == "touch"]
            if len(prior_t) < 60 or len(recent_t) < 30:
                continue
            best = None
            for pid, ps in self.teams[team].players.items():
                if not ps.on_pitch or ps.position == "GK" or self._hot_until.get(pid, -1) > self.elapsed:
                    continue
                before = sum(1 for r in prior_t if r.player == pid)
                if before < 5:
                    continue
                now = sum(1 for r in recent_t if r.player == pid)
                expected = before / len(prior_t) * len(recent_t)
                ratio = (now + HOT_PRIOR) / (expected + HOT_PRIOR)
                decisive = [r for r in recent if r.player == pid and r.kind in DECISIVE]
                if (now >= T["hot_streak_min_touches"] and len(decisive) >= T["hot_streak_min_decisive"]
                        and ratio >= T["hot_streak_ratio"] and (best is None or ratio > best[0])):
                    best = (ratio, pid, now, expected, decisive)
            if best:
                ratio, pid, now, expected, decisive = best
                self._hot_until[pid] = self.elapsed + 1200
                self.emit("hot_streak", 0.55, team, pid, status="start", facts={
                    "player": self._name(pid), "touches_last_12": now,
                    "expected_touches_last_12": round(expected, 1), "ratio": round(ratio, 2),
                    "touch_share_last_12": round(now / len(recent_t), 3),
                    "touch_share_before": round(expected / len(recent_t), 3),
                    "shots_last_12": sum(1 for r in decisive if r.kind == "shot"),
                    "key_passes_last_12": sum(1 for r in decisive if r.kind == "key_pass"),
                    "dribbles_last_12": sum(1 for r in decisive if r.kind == "dribble"),
                    "goals_last_12": sum(1 for r in decisive if r.kind == "goal"),
                }, evidence=[r.eid for r in decisive][-8:])

    # ------------------------------------------------------------- outputs
    def possession_pct(self) -> dict[str, float]:
        secs = {t: s.possession_seconds for t, s in self.teams.items()}
        if self.cur_poss:
            secs[self.cur_poss[0]] += self.elapsed - self.cur_poss[1]
        total = sum(secs.values()) or 1.0
        return {t: round(100 * v / total, 1) for t, v in secs.items()}

    def team_summary(self) -> dict:
        poss = self.possession_pct()
        f3 = {t: s.final_third_passes for t, s in self.teams.items()}
        tot = sum(f3.values()) or 1
        return {t: s.to_dict(poss[t], round(100 * f3[t] / tot, 1)) for t, s in self.teams.items()}

    def snapshot(self) -> dict:
        players = [p.to_dict() for t in self.teams.values() for p in t.players.values()
                   if p.touches or p.on_pitch]
        return {
            "match_id": self.match_id, "period": self.period, "clock": self.clock,
            "minute": round(self.minute, 1), "score": dict(self.score),
            "home": self.home, "away": self.away,
            "teams": self.team_summary(), "momentum": round(self.momentum, 1), "regime": self.regime,
            "pressing": {t: {"active": s["active"], "rate": round(s.get("rate", 0.0), 2)}
                         for t, s in self._press.items()},
            "players": players, "series": self.series,
        }
