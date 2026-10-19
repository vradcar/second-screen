"""Possession-by-possession football match simulator.

Produces a provider-style event feed (what a data vendor would send) plus a
separate truth record (hidden arcs, tactical blocks) for evaluation.

Coordinate frame of emitted events: 105 x 68 m, normalised so the home team
always attacks toward x = 105, in both halves.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from statistics import mean

from secondscreen import metrics
from secondscreen.simulator.arcs import ArcDirector
from secondscreen.simulator.teams import Club, Player

HALF = 2700.0
PX, PY = metrics.PITCH_X, metrics.PITCH_Y

# How likely each position is to be on the ball, by zone (possessor's frame).
ZONE_WEIGHTS = {
    "def": {"GK": 1.0, "CB": 3.0, "RB": 2.0, "LB": 2.0, "DM": 2.5, "CM": 1.5, "RW": 0.4, "LW": 0.4, "ST": 0.2},
    "mid": {"GK": 0.05, "CB": 1.2, "RB": 1.8, "LB": 1.8, "DM": 2.5, "CM": 3.0, "RW": 1.8, "LW": 1.8, "ST": 1.0},
    "att": {"GK": 0.0, "CB": 0.2, "RB": 1.2, "LB": 1.2, "DM": 0.8, "CM": 2.2, "RW": 2.6, "LW": 2.6, "ST": 3.0},
}
# Probability the defending side applies pressure, by its block and the possessor's zone.
BLOCK_PRESS = {
    "high_press": {"def": 0.50, "mid": 0.38, "att": 0.24},
    "mid_block": {"def": 0.18, "mid": 0.34, "att": 0.30},
    "low_block": {"def": 0.08, "mid": 0.18, "att": 0.40},
}
# Average running speed while on the pitch (m/s).
RUN_RATE = {"GK": 1.0, "CB": 2.15, "RB": 2.4, "LB": 2.4, "DM": 2.45, "CM": 2.55,
            "RW": 2.35, "LW": 2.35, "ST": 2.25}
SNAPSHOT_EVERY = 300.0


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def zone_of(x: float) -> str:
    return "def" if x < 35 else ("mid" if x < 70 else "att")


def flip(x: float, y: float) -> tuple[float, float]:
    """Convert a position from one team's attacking frame to the other's."""
    return PX - x, PY - y


class MatchSimulator:
    def __init__(self, home: Club, away: Club, seed: int = 7, match_id: str | None = None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.home, self.away = home, away
        self.clubs = {home.team_id: home, away.team_id: away}
        self.match_id = match_id or f"SS{seed:05d}"
        self.events: list[dict] = []
        self.seq = 0
        self.t = 0.0          # game clock in seconds (restarts at 2700 for the 2nd half)
        self.elapsed = 0.0    # monotonic seconds of play, for replay timing
        self.period = 1
        self.period_end = HALF
        self.score = {home.team_id: 0, away.team_id: 0}
        self.possession_id = 0
        self.arcs = ArcDirector(self.rng, home, away)
        self.momentum_until: dict[str, float] = {}
        self.blocks: dict[str, str] = {}
        self.sub_minutes = {c.team_id: sorted(self.rng.sample(range(57, 86), 3)) for c in (home, away)}
        self.next_snapshot = SNAPSHOT_EVERY
        self.last_completed: tuple[int, Player, Player] | None = None
        self.last_team: str | None = None
        self.truth: dict = {"tactical_timeline": [], "goals": [], "momentum_windows": [], "cards": []}

    # ------------------------------------------------------------------ helpers
    @property
    def minute(self) -> float:
        return self.t / 60.0

    def other(self, team_id: str) -> str:
        return self.away.team_id if team_id == self.home.team_id else self.home.team_id

    def to_abs(self, frame_team: str, x: float, y: float) -> tuple[float, float]:
        if frame_team == self.home.team_id:
            return round(x, 1), round(y, 1)
        return round(PX - x, 1), round(PY - y, 1)

    def clock(self) -> str:
        cap = 45 if self.period == 1 else 90
        m, s = int(self.t // 60), int(self.t % 60)
        if m >= cap:
            return f"{cap}+{m - cap + 1}'"
        return f"{m:02d}:{s:02d}"

    def emit(self, etype: str, team_id: str | None = None, player: Player | None = None,
             at: tuple[str, float, float] | None = None, end: tuple[str, float, float] | None = None,
             **fields) -> dict:
        self.seq += 1
        ev = {
            "event_id": f"{self.match_id}-{self.seq:05d}",
            "match_id": self.match_id,
            "seq": self.seq,
            "period": self.period,
            "clock": self.clock(),
            "clock_seconds": round(self.t, 1),
            "elapsed_seconds": round(self.elapsed, 1),
            "type": etype,
        }
        if team_id:
            ev["team_id"] = team_id
        if player:
            ev["player_id"] = player.player_id
            ev["player_name"] = player.name
        if at:
            ev["x"], ev["y"] = self.to_abs(*at)
        if end:
            ev["end_x"], ev["end_y"] = self.to_abs(*end)
        ev.update({k: v for k, v in fields.items() if v is not None})
        ev["score"] = dict(self.score)
        ev["possession_id"] = self.possession_id
        self.events.append(ev)
        return ev

    def mods(self, team_id: str):
        m, involve = self.arcs.mods(self.minute, team_id)
        if self.momentum_until.get(team_id, -1) > self.elapsed:
            m["press"] += 0.08
            m["shot_intent"] += 0.03
        n = len(self.clubs[team_id].on_pitch())
        if n < 11:  # down to ten
            m["press"] -= 0.06 * (11 - n)
            m["pass_acc"] -= 0.2 * (11 - n)
        return m, involve

    def current_block(self, team_id: str) -> str:
        m, _ = self.mods(team_id)
        diff = self.score[team_id] - self.score[self.other(team_id)]
        if m.get("force_block"):
            block = m["force_block"]
        elif self.minute >= 70 and diff < 0:
            block = "high_press"
        elif self.minute >= 75 and diff > 0:
            block = "low_block"
        else:
            block = self.clubs[team_id].style["block"]
        if self.blocks.get(team_id) != block:
            self.blocks[team_id] = block
            self.truth["tactical_timeline"].append(
                {"minute": round(self.minute, 1), "period": self.period, "team_id": team_id, "block": block})
        return block

    # --------------------------------------------------------------- time & body
    def advance(self, dt: float) -> None:
        self.t += dt
        self.elapsed += dt
        for club in (self.home, self.away):
            m, _ = self.mods(club.team_id)
            block = self.blocks.get(club.team_id, club.style["block"])
            intensity = {"high_press": 1.08, "low_block": 0.95}.get(block, 1.0)
            for p in club.on_pitch():
                p.distance_m += RUN_RATE[p.position] * intensity * (1 - 0.22 * p.fatigue) * dt
                rate = (0.62 / 5400) * (70 / p.stamina) * intensity * (1 + m.get("fatigue_rate", 0.0))
                p.fatigue = min(1.0, p.fatigue + rate * dt)
        if self.elapsed >= self.next_snapshot:
            self.next_snapshot += SNAPSHOT_EVERY
            self.emit("physical_snapshot", players=[
                {"player_id": p.player_id, "team_id": p.team_id, "distance_m": round(p.distance_m),
                 "top_speed_kmh": round(p.top_speed_kmh, 1)}
                for c in (self.home, self.away) for p in c.on_pitch()
            ])

    def sprint(self, p: Player, boost: float = 0.0) -> float:
        speed = clamp(22.0 + p.eff("pace") * 0.11 + boost + self.rng.gauss(0, 1.2), 18.0, 36.8)
        p.top_speed_kmh = max(p.top_speed_kmh, speed)
        return round(speed, 1)

    # ---------------------------------------------------------- player picking
    def pick_player(self, team_id: str, x: float, y: float, exclude: Player | None = None,
                    outfield: bool = False) -> Player:
        club = self.clubs[team_id]
        _, involve = self.mods(team_id)
        weights = ZONE_WEIGHTS[zone_of(x)]
        cands, ws = [], []
        for p in club.on_pitch():
            if p is exclude or (outfield and p.position == "GK"):
                continue
            w = weights[p.position]
            if p.position in ("RB", "RW") and y < 28:
                w *= 1.6
            elif p.position in ("LB", "LW") and y > 40:
                w *= 1.6
            w *= involve.get(p.player_id, 1.0)
            if w > 0:
                cands.append(p)
                ws.append(w)
        return self.rng.choices(cands, ws)[0]

    def pick_defender(self, def_team: str, x: float, y: float) -> Player:
        """Defender near a point given in the *possessor's* frame."""
        fx, fy = flip(x, y)
        return self.pick_player(def_team, fx, fy, outfield=True)

    def press_prob(self, def_team: str, x: float) -> float:
        zone = zone_of(x)
        block = self.current_block(def_team)
        on = [p for p in self.clubs[def_team].on_pitch() if p.position != "GK"]
        avg_press = mean(p.pressing for p in on) / 70
        avg_fat = mean(p.fatigue for p in on)
        m, _ = self.mods(def_team)
        p = BLOCK_PRESS[block][zone] * avg_press * (1 - 0.45 * avg_fat)
        p += m["press"] * (1.0 if zone != "att" else 0.4)
        return clamp(p, 0.02, 0.85)

    # --------------------------------------------------------------- main loop
    def run(self) -> tuple[list[dict], dict]:
        self.emit("match_start", home=self.home.public(), away=self.away.public(),
                  venue="Halcyon Park", competition="Second Screen Demo League",
                  pitch={"length_m": PX, "width_m": PY,
                         "frame": "home team always attacks toward x=105"})
        for period in (1, 2):
            self.period = period
            self.t = 0.0 if period == 1 else HALF
            stoppage = self.rng.randint(60, 240) if period == 1 else self.rng.randint(180, 420)
            self.period_end = self.t + HALF + stoppage
            for tid in self.clubs:
                self.current_block(tid)
            self.emit("period_start", added_time_min=None)
            team = self.home.team_id if period == 1 else self.away.team_id
            state = (team, PX / 2, PY / 2, "kickoff", None)
            while state is not None:
                state = self.play_possession(*state)
            self.emit("period_end", added_time_min=round(stoppage / 60))
        self.emit("match_end")
        truth = {
            "match_id": self.match_id,
            "seed": self.seed,
            "final_score": dict(self.score),
            "arcs": self.arcs.to_list(),
            **self.truth,
        }
        return self.events, truth

    def dead_ball(self, team_id: str) -> None:
        """Hook for things that happen while the ball is out: subs, late surge."""
        arc = self.arcs.maybe_late_surge(self.minute, self.score)
        if arc:
            self.current_block(arc.team_id)
        for tid, club in self.clubs.items():
            mins = self.sub_minutes[tid]
            if self.period == 2 and mins and self.minute >= mins[0]:
                mins.pop(0)
                self.substitute(club)

    def substitute(self, club: Club) -> None:
        bench = club.bench()
        tired = sorted((p for p in club.on_pitch() if p.position != "GK"),
                       key=lambda p: p.fatigue, reverse=True)
        if not bench or not tired:
            return
        off = tired[0]
        same = [b for b in bench if b.position == off.position]
        on = same[0] if same else next((b for b in bench if b.position != "GK"), None)
        if on is None:
            return
        on.position = off.position  # slot into the same role
        off.on_pitch, on.on_pitch = False, True
        self.advance(self.rng.uniform(20, 40))
        self.emit("substitution", club.team_id, on, player_off_id=off.player_id,
                  player_off_name=off.name, reason="tactical")

    # ------------------------------------------------------------- possession
    def play_possession(self, team_id: str, x: float, y: float, restart: str, holder: Player | None):
        """Play one spell of possession. Returns the next state, or None when the period ends."""
        if self.t >= self.period_end:
            return None
        rng = self.rng
        opp = self.other(team_id)
        self.possession_id += 1
        if self.last_team is not None and self.last_team != team_id:
            self.emit("possession_change", team_id, at=(team_id, x, y), reason=restart,
                      from_team_id=self.last_team)
        self.last_team = team_id
        if restart in ("kickoff", "goal_kick", "throw_in", "keeper", "free_kick", "corner"):
            self.dead_ball(team_id)
            self.advance({"kickoff": 3, "goal_kick": 14, "throw_in": 8, "keeper": 6,
                          "free_kick": 18, "corner": 25}[restart] * rng.uniform(0.7, 1.4))
        self.emit("possession_start", team_id, at=(team_id, x, y), start_type=restart)

        if restart == "corner":
            return self.play_corner(team_id)
        if restart == "goal_kick":
            holder = self.clubs[team_id].goalkeeper()
        holder = holder or self.pick_player(team_id, x, y)
        counter = restart in ("interception", "tackle") and x > 52
        actions = 0

        while True:
            if self.t >= self.period_end and actions > 0:
                return None
            actions += 1
            m, _ = self.mods(team_id)
            is_counter = counter and actions <= 4
            pressed = rng.random() < self.press_prob(opp, x)
            if pressed:
                presser = self.pick_defender(opp, x, y)
                self.advance(rng.uniform(0.4, 1.2))
                self.emit("pressure", opp, presser, at=(team_id, x, y), on_player_id=holder.player_id)
                if rng.random() < 0.035 and not metrics.in_box(x, y):
                    return self.foul(team_id, holder, presser, x, y)
                # Pressing sides hunt in packs: a second player closes down.
                if self.blocks.get(opp) == "high_press" and zone_of(x) != "att" and rng.random() < 0.4:
                    second = self.pick_defender(opp, x, y)
                    if second is not presser:
                        self.emit("pressure", opp, second, at=(team_id, x, y), on_player_id=holder.player_id)

            action = self.choose_action(holder, x, y, pressed, is_counter, m)
            if action == "shot":
                return self.do_shot(team_id, holder, x, y, "counter" if is_counter else "open_play")
            if action == "carry":
                res = self.do_carry(team_id, holder, x, y, pressed, is_counter, m)
                if res[0] != "kept":
                    return res[1]
                _, x, y = res
                continue
            res = self.do_pass(team_id, holder, x, y, pressed, is_counter, m)
            if res[0] != "kept":
                return res[1]
            _, holder, x, y = res

    def choose_action(self, holder: Player, x: float, y: float, pressed: bool, counter: bool, m) -> str:
        if holder.position == "GK":
            return "pass"
        p_shot = 0.0
        if x >= 76 and abs(y - PY / 2) <= 24:
            xg = metrics.expected_goals(x, y)
            p_shot = 0.028 + 0.3 * xg + m["shot_intent"]
            if pressed:
                p_shot *= 0.8
            if counter:
                p_shot *= 1.15
            p_shot = clamp(p_shot, 0.0, 0.8)
        if self.rng.random() < p_shot:
            return "shot"
        p_carry = 0.13 + (holder.dribbling - 70) / 250 + (0.12 if counter else 0) + (0.05 if x > 60 else 0)
        if m.get("star_id") == holder.player_id:
            p_carry += 0.1
        return "carry" if self.rng.random() < p_carry else "pass"

    # ------------------------------------------------------------------ pass
    def do_pass(self, team_id, holder, x, y, pressed, counter, m):
        rng = self.rng
        opp = self.other(team_id)
        club = self.clubs[team_id]
        zone = zone_of(x)
        directness = club.style["directness"] + m["directness"]
        if holder.position == "GK":
            p_long = 0.2 + 0.6 * directness + (0.2 if pressed else 0)
        else:
            p_long = directness * {"def": 0.32, "mid": 0.18, "att": 0.06}[zone] + (0.12 if pressed and zone == "def" else 0)
        long_ball = rng.random() < p_long

        if long_ball:
            dist = rng.uniform(24, 52)
            ang = rng.gauss(0, 0.45)
        else:
            dist = clamp(rng.lognormvariate(math.log(12), 0.4), 4, 30)
            fwd = 0.45 + 0.25 * directness + (0.2 if counter else 0)
            r = rng.random()
            if r < fwd:
                ang = rng.gauss(0, 0.55)
            elif r < fwd + 0.14:
                ang = rng.gauss(math.pi, 0.6)
            else:
                ang = rng.choice((1, -1)) * rng.gauss(math.pi / 2, 0.35)
        # Wide players in the final third tend to cross into the box.
        cross = holder.position in ("RW", "LW", "RB", "LB") and x > 80 and abs(y - PY / 2) > 16 and rng.random() < 0.45
        if cross:
            ex, ey = rng.uniform(92, 101), rng.uniform(26, 42)
            dist = math.hypot(ex - x, ey - y)
        else:
            ex, ey = x + dist * math.cos(ang), y + dist * math.sin(ang)
            if ex > 96 and PY / 2 - 20 < ey < PY / 2 + 20 and rng.random() < 0.85:
                ex = rng.uniform(86, 96)  # defenders deny space in the six-yard box
        out = ey < 0 or ey > PY or ex > PX
        ex, ey = clamp(ex, 1.0, PX - 1.0), clamp(ey, 0.5, PY - 0.5)
        dist = math.hypot(ex - x, ey - y)
        progressive = ex - x
        box = metrics.in_box(ex, ey)

        base = metrics.pass_logit(dist, pressed, progressive, box)
        opp_def = mean(p.defending for p in self.clubs[opp].on_pitch()) / 70
        logit = base + (holder.eff("passing") - 70) * 0.035 + m["pass_acc"] - (opp_def - 1) * 1.0
        if cross:
            logit -= 0.9
        success = (not out or rng.random() < 0.5) and rng.random() < metrics.sigmoid(logit)
        ball_speed = round(clamp(28 + dist * 1.15 + rng.gauss(0, 4), 18, 95), 1)
        self.advance(dist / (ball_speed / 3.6) + rng.uniform(1.0, 3.0) / club.style["tempo"])

        common = dict(distance_m=round(dist, 1), ball_speed_kmh=ball_speed, under_pressure=pressed,
                      height="high" if (long_ball or cross) else "ground", cross=cross or None,
                      progressive_m=round(progressive, 1))
        if success:
            recipient = self.pick_player(team_id, ex, ey, exclude=holder)
            self.emit("pass", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                      outcome="complete", recipient_id=recipient.player_id,
                      recipient_name=recipient.name, **common)
            self.last_completed = (self.possession_id, holder, recipient)
            if cross and rng.random() < 0.3:
                hx, hy = ex, ey
                return ("shot", self.do_shot(team_id, recipient, hx, hy, "open_play", body_part="head"))
            return ("kept", recipient, ex, ey)

        if out:
            self.emit("pass", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                      outcome="out", **common)
            if ex >= PX - 1.5:
                return ("lost", (opp, 6.0, 34.0, "goal_kick", None))
            fx, fy = flip(ex, ey)
            return ("lost", (opp, fx, 0.5 if fy < 34 else PY - 0.5, "throw_in", None))

        self.emit("pass", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                  outcome="intercepted", **common)
        interceptor = self.pick_defender(opp, ex, ey)
        fx, fy = flip(ex, ey)
        self.emit("interception", opp, interceptor, at=(opp, fx, fy))
        return ("lost", (opp, fx, fy, "interception", interceptor))

    # ----------------------------------------------------------------- carry
    def do_carry(self, team_id, holder, x, y, pressed, counter, m):
        rng = self.rng
        opp = self.other(team_id)
        if x > 75:  # defences are compact near their own box
            dist = rng.uniform(3, 10) if counter else rng.uniform(2, 7)
        else:
            dist = rng.uniform(10, 30) if counter else rng.uniform(4, 16)
        ang = rng.gauss(0, 0.5)
        ex = clamp(x + dist * math.cos(ang), 1, PX - 12)
        ey = clamp(y + dist * math.sin(ang), 1, PY - 1)
        star = m.get("star_id") == holder.player_id
        speed = self.sprint(holder, boost=1.0 if counter else -3.0)
        self.advance(dist / (speed / 3.6) + 0.5)

        if pressed or rng.random() < 0.22:
            defender = self.pick_defender(opp, ex, ey)
            dribble = holder.eff("dribbling") + (m["star_dribble"] if star else 0)
            p_tackle = clamp(0.42 + (defender.eff("defending") - dribble) / 180, 0.12, 0.8)
            if rng.random() < p_tackle:
                # Some tackles are fouls.
                foul_p = 0.04 if metrics.in_box(ex, ey) else 0.32
                if rng.random() < foul_p:
                    return ("stop", self.foul(team_id, holder, defender, ex, ey))
                self.emit("carry", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                          distance_m=round(dist, 1), speed_kmh=speed)
                fx, fy = flip(ex, ey)
                self.emit("tackle", opp, defender, at=(opp, fx, fy), outcome="won",
                          on_player_id=holder.player_id)
                return ("lost", (opp, fx, fy, "tackle", defender))
            self.emit("carry", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                      distance_m=round(dist, 1), speed_kmh=speed)
            fx, fy = flip(ex, ey)
            self.emit("tackle", opp, defender, at=(opp, fx, fy), outcome="beaten",
                      on_player_id=holder.player_id)
            self.emit("dribble", team_id, holder, at=(team_id, ex, ey), outcome="success",
                      beat_player_id=defender.player_id)
            return ("kept", ex, ey)

        self.emit("carry", team_id, holder, at=(team_id, x, y), end=(team_id, ex, ey),
                  distance_m=round(dist, 1), speed_kmh=speed)
        return ("kept", ex, ey)

    def foul(self, team_id, victim, offender, x, y):
        """Foul by `offender` on `victim` (position in victim's frame). Returns next state."""
        rng = self.rng
        opp = offender.team_id
        fx, fy = flip(x, y)
        self.emit("foul", opp, offender, at=(opp, fx, fy), on_player_id=victim.player_id)
        card_p = 0.45 if metrics.in_box(x, y) else 0.17
        if rng.random() < card_p:
            offender.yellow_cards += 1
            card = "yellow" if offender.yellow_cards < 2 else "second_yellow"
            self.emit("card", opp, offender, card=card)
            self.truth["cards"].append({"minute": round(self.minute, 1), "player_id": offender.player_id, "card": card})
            if card == "second_yellow":
                offender.on_pitch, offender.sent_off = False, True
        if metrics.in_box(x, y):
            self.dead_ball(team_id)
            self.advance(rng.uniform(50, 80))
            taker = max(self.clubs[team_id].on_pitch(), key=lambda p: p.finishing)
            self.emit("penalty_awarded", team_id, taker)
            return self.do_shot(team_id, taker, PX - 11, PY / 2, "penalty")
        if x > 78 and abs(y - PY / 2) < 18 and rng.random() < 0.4:
            self.dead_ball(team_id)
            self.advance(rng.uniform(25, 45))
            taker = max(self.clubs[team_id].on_pitch(), key=lambda p: p.passing + p.finishing)
            return self.do_shot(team_id, taker, x, y, "free_kick")
        return (team_id, x, y, "free_kick", victim)

    # ------------------------------------------------------------------ shot
    def do_shot(self, team_id, shooter, x, y, situation, body_part="foot"):
        rng = self.rng
        opp = self.other(team_id)
        m, _ = self.mods(team_id)
        xg = metrics.expected_goals(x, y, body_part=body_part, situation=situation)
        dist, _ = metrics.shot_geometry(x, y)
        gk = self.clubs[opp].goalkeeper()
        finish = shooter.eff("finishing")
        if body_part == "head":
            finish = (finish + shooter.eff("defending")) / 2
        p_goal = xg * (1 + (finish - 70) / 60 + m["finishing"]
                       + (m["star_finish"] if m.get("star_id") == shooter.player_id else 0))
        p_goal *= 0.72 * (1 - (gk.eff("defending") - 70) / 150)
        p_goal = clamp(p_goal, 0.005, 0.92)
        shot_speed = round(clamp(55 + finish * 0.35 + dist * 0.6 + rng.gauss(0, 8), 40, 128), 1)
        if body_part == "head":
            shot_speed = round(shot_speed * 0.6, 1)
        self.advance(rng.uniform(0.5, 1.5))
        assist = None
        if self.last_completed and self.last_completed[0] == self.possession_id and self.last_completed[2] is shooter:
            assist = self.last_completed[1]

        common = dict(xg_inputs={"distance_m": round(dist, 1), "body_part": body_part, "situation": situation},
                      shot_speed_kmh=shot_speed, body_part=body_part, situation=situation)

        if rng.random() < p_goal:
            self.emit("shot", team_id, shooter, at=(team_id, x, y), end=(team_id, PX, rng.uniform(30.5, 37.5)),
                      outcome="goal", **common)
            self.score[team_id] += 1
            self.emit("goal", team_id, shooter, at=(team_id, x, y),
                      assist_player_id=assist.player_id if assist else None,
                      assist_name=assist.name if assist else None)
            self.truth["goals"].append({"minute": round(self.minute, 1), "period": self.period,
                                        "team_id": team_id, "player_id": shooter.player_id,
                                        "situation": situation, "xg": xg})
            self.momentum_until[opp] = self.elapsed + 8 * 60
            self.truth["momentum_windows"].append(
                {"team_id": opp, "from_minute": round(self.minute, 1), "minutes": 8, "trigger": "conceded"})
            self.advance(rng.uniform(45, 75))
            return (opp, PX / 2, PY / 2, "kickoff", None)

        r = rng.random()
        blocked_p = 0.12 if situation == "penalty" else clamp(0.18 + dist / 120, 0.18, 0.4)
        if situation != "penalty" and r < blocked_p:
            self.emit("shot", team_id, shooter, at=(team_id, x, y), outcome="blocked", **common)
            blocker = self.pick_defender(opp, x, y)
            fx, fy = flip(x, y)
            self.emit("block", opp, blocker, at=(opp, fx, fy))
            if rng.random() < 0.4:
                return (team_id, PX, 0.0, "corner", None)
            return (opp, clamp(fx + 6, 3, 30), fy, "loose_ball", None)
        if r < blocked_p + 0.45 * (1 - blocked_p):
            ey = rng.choice((rng.uniform(25, 30.2), rng.uniform(37.8, 43)))
            self.emit("shot", team_id, shooter, at=(team_id, x, y), end=(team_id, PX, ey),
                      outcome="off_target", **common)
            return (opp, 6.0, 34.0, "goal_kick", None)
        self.emit("shot", team_id, shooter, at=(team_id, x, y), end=(team_id, PX, rng.uniform(30.8, 37.2)),
                  outcome="saved", **common)
        fx, fy = flip(PX - 1, PY / 2)
        self.emit("save", opp, gk, at=(opp, fx, fy), shot_speed_kmh=shot_speed)
        if rng.random() < 0.3:
            return (team_id, PX, 0.0, "corner", None)
        return (opp, 8.0, 34.0, "keeper", gk)

    def play_corner(self, team_id: str):
        rng = self.rng
        opp = self.other(team_id)
        side_y = rng.choice((0.5, PY - 0.5))
        taker = max((p for p in self.clubs[team_id].on_pitch() if p.position != "GK"),
                    key=lambda p: p.passing)
        self.emit("corner", team_id, taker, at=(team_id, PX - 0.5, side_y))
        if rng.random() < 0.3:
            target = max((p for p in self.clubs[team_id].on_pitch() if p.position in ("CB", "ST")),
                         key=lambda p: p.defending + p.finishing)
            hx, hy = rng.uniform(94, 100), rng.uniform(28, 40)
            self.emit("pass", team_id, taker, at=(team_id, PX - 0.5, side_y), end=(team_id, hx, hy),
                      outcome="complete", recipient_id=target.player_id, recipient_name=target.name,
                      distance_m=round(math.hypot(PX - hx, side_y - hy), 1), ball_speed_kmh=62.0,
                      under_pressure=False, height="high", cross=True, set_piece="corner")
            self.last_completed = (self.possession_id, taker, target)
            return self.do_shot(team_id, target, hx, hy, "open_play", body_part="head")
        clearer = self.pick_player(opp, 12, 34)
        cx, cy = rng.uniform(15, 35), rng.uniform(10, 58)
        self.emit("clearance", opp, clearer, at=(opp, 8.0, 34.0), end=(opp, cx, cy))
        return (opp, cx, cy, "loose_ball", None)


def simulate(seed: int = 7, home: Club | None = None, away: Club | None = None):
    from secondscreen.simulator.teams import default_clubs
    if home is None or away is None:
        home, away = default_clubs()
    return MatchSimulator(home, away, seed=seed).run()
