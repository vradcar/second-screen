"""Running play-by-play: the commentator talks through the whole match, not just the big moments.

Built from the event feed alone (no model call, so it keeps up with live play and every word
is grounded in an event): who has the ball, where it goes, who wins it back, set pieces, cards,
subs, kick-off and the whistles. In the lulls the co-commentator drops in a stat from the stats
engine. Big moments (goals, red cards, big chances) are left to the spotter's calls and the
agents, so play-by-play never talks over them.

Lines come at a steady match-time cadence; the viewer's commentary box plays the ones it has
room for at the current speed, so at 1x you hear nearly all of them and at 5x every few.
"""
from __future__ import annotations

from secondscreen import metrics

GAP = 5.0            # match seconds between running lines
COLOUR_EVERY = 6     # every Nth running line is a colour line (stat), when there's one to say
BIG_XG = 0.30        # shots at or above this are called by the spotter instead

T = {
    "en": {
        "pass": ["{p} to {r}", "{p} finds {r}", "{p} plays it to {r}", "{p} lays it off to {r}"],
        "long": ["{p}, long ball for {r}", "{p} goes long, looking for {r}"], "box": ["{p} slides it into the box for {r}", "{p} picks out {r} in the box", "{p} puts it into the area for {r}"],
        "third": "{p} finds {r} in the final third", "chain": "{a}... {b}... on to {c}",
        "lost": ["{p}'s pass is cut out", "{p} gives it away", "loose from {p}", "{p} can't find his man"],
        "carry": ["{p} drives forward", "{p} carries it on", "{p}, running at them"],
        "dribble": ["{p} skips past his man", "lovely feet from {p}"],
        "dribble_fail": "{p} tries to go past him, no way through",
        "tackle": ["good tackle from {p}", "{p} wins it", "strong challenge from {p}"],
        "intercept": ["{p} nips in", "{p} reads it", "{p} steps in to win it"],
        "clear": ["cleared by {p}", "{p} hacks it clear"],
        "shot_saved": "{p} shoots... and it's saved.", "shot_wide": "{p} lets fly... wide of the target.",
        "shot_blocked": "{p} shoots... blocked.", "shot_post": "{p} shoots... off the woodwork!",
        "foul": "Foul by {p}. Free kick.", "yellow": "Yellow card for {p}.", "corner": "Corner to {t}.",
        "sub": "A change for {t}: {on} comes on for {off}.",
        "ko1": "And we're under way!", "ko2": "We're back under way for the second half.",
        "ht": "There's the whistle for half-time. {state}.", "ft": "And there's the final whistle! {state}.",
        "level": "Level at {a}-{b}", "lead": "{t} lead {a}-{b}",
        "c_poss": "{t} have had {n}% of the ball so far.",
        "c_shots": "Shots so far: {t} {a}, {o} {b}.",
        "c_xg": "On expected goals it's {t} {a}, {o} {b}. {judge}",
        "c_xg_close": "Not much between them.", "c_xg_gap": "{t} have created the better chances.",
        "c_press": "{t} have won it back high up the pitch {n} times already. That press is working.",
        "c_mom": "It's all {t} at the moment.",
    },
    "es": {
        "pass": "{p} para {r}", "long": "{p}, balón largo para {r}", "box": "{p} la mete al área para {r}",
        "third": "{p} encuentra a {r} en tres cuartos", "chain": "{a}... {b}... para {c}",
        "lost": "Interceptan el pase de {p}", "carry": "{p} conduce hacia adelante", "dribble": "{p} se va de su marca",
        "dribble_fail": "{p} intenta el regate, no pasa", "tackle": "buena entrada de {p}",
        "intercept": "{p} la corta", "clear": "despeja {p}",
        "shot_saved": "Dispara {p}... y para el portero.", "shot_wide": "Dispara {p}... se va fuera.",
        "shot_blocked": "Dispara {p}... bloqueado.", "shot_post": "Dispara {p}... ¡al palo!",
        "foul": "Falta de {p}.", "yellow": "Amarilla para {p}.", "corner": "Córner para {t}.",
        "sub": "Cambio en {t}: entra {on}, sale {off}.",
        "ko1": "¡Rueda el balón!", "ko2": "Arranca la segunda parte.",
        "ht": "Final de la primera parte. {state}.", "ft": "¡Final del partido! {state}.",
        "level": "Empate a {a}", "lead": "{t} gana {a}-{b}",
        "c_poss": "{t} ha tenido el {n}% del balón.", "c_shots": "Tiros: {t} {a}, {o} {b}.",
        "c_xg": "En goles esperados, {t} {a}, {o} {b}. {judge}", "c_xg_close": "Muy igualado.",
        "c_xg_gap": "{t} ha generado las mejores ocasiones.",
        "c_press": "{t} ya ha recuperado arriba {n} veces. La presión funciona.", "c_mom": "Ahora mismo, todo es de {t}.",
    },
    "fr": {
        "pass": "{p} pour {r}", "long": "{p}, ballon long pour {r}", "box": "{p} glisse dans la surface pour {r}",
        "third": "{p} trouve {r} dans les trente derniers mètres", "chain": "{a}... {b}... pour {c}",
        "lost": "La passe de {p} est interceptée", "carry": "{p} remonte le terrain", "dribble": "{p} élimine son vis-à-vis",
        "dribble_fail": "{p} tente le dribble, ça ne passe pas", "tackle": "beau tacle de {p}",
        "intercept": "{p} intercepte", "clear": "dégagement de {p}",
        "shot_saved": "{p} frappe... arrêté.", "shot_wide": "{p} frappe... à côté.",
        "shot_blocked": "{p} frappe... contré.", "shot_post": "{p} frappe... sur le poteau !",
        "foul": "Faute de {p}.", "yellow": "Carton jaune pour {p}.", "corner": "Corner pour {t}.",
        "sub": "Changement pour {t} : {on} remplace {off}.",
        "ko1": "C'est parti !", "ko2": "La seconde période est lancée.",
        "ht": "C'est la mi-temps. {state}.", "ft": "Coup de sifflet final ! {state}.",
        "level": "Égalité, {a}-{b}", "lead": "{t} mène {a}-{b}",
        "c_poss": "{t} a eu {n}% de possession.", "c_shots": "Tirs : {t} {a}, {o} {b}.",
        "c_xg": "En expected goals, {t} {a}, {o} {b}. {judge}", "c_xg_close": "Très serré.",
        "c_xg_gap": "{t} s'est créé les meilleures occasions.",
        "c_press": "{t} a déjà récupéré haut {n} fois. Le pressing paie.", "c_mom": "Tout est pour {t} en ce moment.",
    },
}
# Lines that describe the moment itself are said at once; flowing play waits for the cadence.
IMMEDIATE = {"foul", "yellow", "corner", "sub", "ko1", "ko2", "ht", "ft", "shot_saved", "shot_wide",
             "shot_blocked", "shot_post"}


def _sur(name: str | None) -> str:
    return (name or "").split()[-1] if name else ""


class PlayByPlay:
    def __init__(self, engine, langs: list[str]):
        self.engine, self.langs = engine, langs
        self.short: dict[str, str] = {}
        self.buf: list[tuple[str, dict]] = []      # (template key, fields) since the last line
        self.last_at = -1e9
        self.n = 0
        self.colour_turn = 0
        self.said: dict[str, float] = {}   # colour key -> when it was last said

    # ------------------------------------------------------------------ helpers
    def _rel_x(self, team: str, x: float | None) -> float:
        return self.engine.ax(team, x) if x is not None and self.engine.home else (x or 0.0)

    def _state(self, lang: str) -> str:
        sc = dict(self.engine.score)
        if len(sc) != 2:
            return ""
        (a, ga), (b, gb) = sorted(sc.items(), key=lambda kv: -kv[1])
        L = T[lang]
        return L["level"].format(a=ga, b=gb) if ga == gb else L["lead"].format(t=self.short.get(a, a), a=ga, b=gb)

    def _line(self, at: float, key: str, fields: dict, role: str = "commentator", kind: str = "pbp") -> dict:
        text = {}
        for lang in self.langs:
            f = {k: (v(lang) if callable(v) else v) for k, v in fields.items()}
            tpl = T[lang][key]
            tpl = tpl[self.n % len(tpl)] if isinstance(tpl, list) else tpl
            s = tpl.format(**f)
            text[lang] = s[0].upper() + s[1:] if s else s
        return {"at": at, "role": role, "kind": kind, "key": key, "text": text}

    # ------------------------------------------------------------------ feed
    def feed(self, ev: dict) -> list[dict]:
        """Call after the engine has ingested `ev`. Returns lines to schedule (usually none or one)."""
        t, at = ev["type"], ev["elapsed_seconds"]
        team, p = ev.get("team_id"), _sur(ev.get("player_name"))
        out: list[dict] = []

        if t == "match_start":
            self.short = {ev["home"]["team_id"]: ev["home"]["short_name"], ev["away"]["team_id"]: ev["away"]["short_name"]}
            return out
        if t == "period_start":
            return [self._mark(at, self._line(at, "ko1" if ev["period"] == 1 else "ko2", {}))]
        if t in ("period_end", "match_end"):
            if t == "period_end" and ev["period"] == 2:
                return out
            key = "ht" if t == "period_end" else "ft"
            return [self._mark(at, self._line(at, key, {"state": self._state}))]

        tname = self.short.get(team, team)
        if t == "pass":
            r = _sur(ev.get("recipient_name"))
            if ev.get("outcome") != "complete":
                self.buf.append(("lost", {"p": p}))
            elif self._rel_x(team, ev.get("end_x")) >= metrics.BOX_X and abs(ev.get("end_y", 34) - 34) < 20:
                self.buf.append(("box", {"p": p, "r": r}))
            elif (ev.get("distance_m") or 0) >= 30:
                self.buf.append(("long", {"p": p, "r": r}))
            elif self._rel_x(team, ev.get("x")) < 70 <= self._rel_x(team, ev.get("end_x")):
                self.buf.append(("third", {"p": p, "r": r}))
            else:
                self.buf.append(("pass", {"p": p, "r": r}))
        elif t == "carry" and self._rel_x(team, ev.get("end_x")) - self._rel_x(team, ev.get("x")) >= 10:
            self.buf.append(("carry", {"p": p}))
        elif t == "dribble":
            self.buf.append(("dribble" if ev.get("outcome") == "success" else "dribble_fail", {"p": p}))
        elif t == "tackle" and ev.get("outcome") == "won":
            self.buf.append(("tackle", {"p": p}))
        elif t == "interception":
            self.buf.append(("intercept", {"p": p}))
        elif t == "clearance":
            self.buf.append(("clear", {"p": p}))
        elif t == "shot" and ev.get("outcome") != "goal":
            x, y = self._rel_x(team, ev.get("x")), ev.get("y", 34) if team == self.engine.home else metrics.PITCH_Y - ev.get("y", 34)
            xg = metrics.expected_goals(x, y, ev.get("body_part", "foot"), ev.get("situation", "open_play"))
            if xg < BIG_XG:                                     # big chances are the spotter's
                key = {"saved": "shot_saved", "blocked": "shot_blocked", "post": "shot_post"}.get(ev.get("outcome"), "shot_wide")
                out.append(self._mark(at, self._line(at, key, {"p": p})))
            self.buf.clear()
            return out
        elif t == "foul":
            return [self._mark(at, self._line(at, "foul", {"p": p}))]
        elif t == "card" and ev.get("card") == "yellow":
            return [self._mark(at, self._line(at, "yellow", {"p": p}))]
        elif t == "corner":
            return [self._mark(at, self._line(at, "corner", {"t": tname}))]
        elif t == "substitution":
            return [self._mark(at, self._line(at, "sub", {"t": tname, "on": p, "off": _sur(ev.get("player_off_name"))}))]
        elif t == "goal":
            self.buf.clear()
            self.last_at = at + 8          # the call and the celebration own the next few seconds
            return out

        if self.buf and at - self.last_at >= GAP:
            self.n += 1
            line = self._colour(at) if self.n % COLOUR_EVERY == 0 else None
            out.append(self._mark(at, line or self._flow(at)))
        return out

    def _mark(self, at: float, line: dict) -> dict:
        self.last_at = at
        self.buf.clear()
        return line

    def _flow(self, at: float) -> dict:
        """Describe the latest passage of play: the last couple of actions, or a chain of names."""
        recent = self.buf[-3:]
        if len(recent) == 3 and all(k == "pass" for k, _ in recent):
            names = [recent[0][1]["p"], recent[1][1]["p"], recent[2][1]["p"], recent[2][1]["r"]]
            a, b, c = names[1], names[2], names[3]
            if len({a, b, c}) == 3:
                return self._line(at, "chain", {"a": a, "b": b, "c": c})
        key, fields = recent[-1]
        # A turnover reads better with who won it: "Steen gives it away... Fontaine nips in".
        if len(recent) >= 2 and recent[-2][0] in ("lost", "tackle", "dribble") and key != recent[-2][0]:
            k0, f0 = recent[-2]
            first, second = self._line(at, k0, f0), self._line(at, key, fields)
            line = dict(second)
            def join(a: str, b: str, who: str = f0.get("p", "")) -> str:
                if who and b.startswith(who + " "):        # same player: "...Fontaine... lays it off to Cardell"
                    b = b[len(who) + 1:]
                    b = b[0].lower() + b[1:]
                return f"{a}... {b}"
            line["text"] = {lang: join(first["text"][lang], second["text"][lang]) for lang in self.langs}
            return line
        return self._line(at, key, fields)

    def _colour(self, at: float) -> dict | None:
        """A stat for the lull, from the stats engine. Rotates topics; skips ones with nothing to say."""
        eng = self.engine
        if not eng.home or eng.minute < 4:
            return None
        ts = eng.team_summary()
        h, a = eng.home, eng.away
        S = lambda tid: self.short.get(tid, tid)  # noqa: E731
        for _ in range(5):
            topic = self.colour_turn % 5
            self.colour_turn += 1
            if at - self.said.get(f"c{topic}", -1e9) < 600:     # don't repeat a stat within 10 minutes
                continue
            self.said[f"c{topic}"] = at
            if topic == 0:
                top = max((h, a), key=lambda x: ts[x]["possession_pct"])
                return self._line(at, "c_poss", {"t": S(top), "n": round(ts[top]["possession_pct"])}, "pundit", "colour")
            if topic == 1 and ts[h]["shots"] + ts[a]["shots"] >= 3:
                return self._line(at, "c_shots", {"t": S(h), "a": ts[h]["shots"], "o": S(a), "b": ts[a]["shots"]},
                                  "commentator", "colour")
            if topic == 2 and ts[h]["xg"] + ts[a]["xg"] >= 0.5:
                gap, better = abs(ts[h]["xg"] - ts[a]["xg"]), (h if ts[h]["xg"] > ts[a]["xg"] else a)
                judge = (lambda lang: T[lang]["c_xg_close"]) if gap < 0.3 else \
                        (lambda lang, b=better: T[lang]["c_xg_gap"].format(t=S(b)))
                return self._line(at, "c_xg", {"t": S(h), "a": f"{ts[h]['xg']:.1f}", "o": S(a), "b": f"{ts[a]['xg']:.1f}",
                                               "judge": judge}, "pundit", "colour")
            if topic == 3:
                top = max((h, a), key=lambda x: ts[x]["high_turnovers"])
                if ts[top]["high_turnovers"] >= 4:
                    return self._line(at, "c_press", {"t": S(top), "n": ts[top]["high_turnovers"]}, "pundit", "colour")
            if topic == 4 and abs(eng.momentum) >= 40:
                return self._line(at, "c_mom", {"t": S(h if eng.momentum > 0 else a)}, "pundit", "colour")
        return None
