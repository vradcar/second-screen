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
COLOUR_EVERY = 4     # every Nth running line is a colour line (team or player), when there's one to say
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
        "c_poss": ["{t} have had {n}% of the ball so far.", "{t} are seeing most of the ball: {n}% of it so far."],
        "c_shots": "{t} have had {a} shots to {o}'s {b}.",
        "c_chances": "{t} have created the better chances so far. {o} have been living dangerously.",
        "c_chances_even": "Not much in it. Neither side has really opened the other up yet.",
        "c_press": "{t} keep winning it back high up the pitch. That press is really working.",
        "c_mom": ["It's all {t} at the moment.", "{t} are well on top here."],
        "p_passes": "{p} has been at the heart of everything: {n} passes already, and hardly one wasted.",
        "p_km": "{p} has covered over {km} kilometres already. He just doesn't stop.",
        "p_shots": "That's {n} shots for {p} today. He's the one carrying the threat.",
        "p_defend": "{p} has won the ball back {n} times today. Reads the game so well.",
        "p_dribbles": "{p} has beaten his man {n} times already. They can't get near him.",
        "p_season_goals": "{p} came into this one with {g} goals this season.",
        "p_season_km": "{p} averages over {km} kilometres a game this season. Never stops running.",
        "i_welcome": "Good afternoon, and welcome to {venue} for {home} against {away}!",
        "i_table": "{hp} against {ap} in the table, so there's plenty riding on this one.",
        "i_star": "{t}'s man to watch is {p}, with {g} goals already this season.",
        "i_threat": "For {t}, it's {p}: {g} goals so far.",
        "i_press": "{t} love to press high. If {o} can play through it, there's space in behind.",
        "i_patient": "{t} like to keep the ball. Will {o} let them?",
        "i_ready": "Here we go!",
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
        "c_poss": "{t} ha tenido el {n}% del balón.", "c_shots": "{t} lleva {a} tiros, {o} {b}.",
        "c_chances": "{t} ha generado las mejores ocasiones. {o} está sufriendo.",
        "c_chances_even": "Partido muy igualado. Nadie ha hecho daño todavía.",
        "c_press": "{t} recupera una y otra vez arriba. La presión está funcionando.", "c_mom": "Ahora mismo, todo es de {t}.",
        "p_passes": "{p} está en todas: ya lleva {n} pases y casi no falla ninguno.",
        "p_km": "{p} ya ha recorrido más de {km} kilómetros. No para.",
        "p_shots": "Ya son {n} tiros de {p}. Es el más peligroso.",
        "p_defend": "{p} ya ha recuperado {n} balones. Qué bien lee el juego.",
        "p_dribbles": "{p} ya ha superado a su marca {n} veces. No hay quien lo pare.",
        "p_season_goals": "{p} llegaba a este partido con {g} goles esta temporada.",
        "p_season_km": "{p} promedia más de {km} kilómetros por partido. No para de correr.",
        "i_welcome": "¡Buenas tardes y bienvenidos a {venue}! {home} contra {away}.",
        "i_table": "El {hp} contra el {ap} de la tabla: hay mucho en juego.",
        "i_star": "En {t}, el hombre a seguir es {p}: ya lleva {g} goles esta temporada.",
        "i_threat": "En {t}, atentos a {p}: {g} goles.",
        "i_press": "A {t} le encanta presionar arriba. Si {o} supera esa presión, tendrá espacios.",
        "i_patient": "{t} quiere el balón y paciencia. Veremos si {o} se lo permite.",
        "i_ready": "¡Vamos allá!",
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
        "c_poss": "{t} a eu {n}% de possession.", "c_shots": "{t} compte {a} tirs, {o} {b}.",
        "c_chances": "{t} s'est créé les meilleures occasions. {o} souffre.",
        "c_chances_even": "Très serré. Personne n'a vraiment fait mal pour l'instant.",
        "c_press": "{t} récupère sans cesse le ballon très haut. Le pressing paie.", "c_mom": "Tout est pour {t} en ce moment.",
        "p_passes": "{p} est partout : déjà {n} passes, et presque aucune de ratée.",
        "p_km": "{p} a déjà parcouru plus de {km} kilomètres. Infatigable.",
        "p_shots": "Déjà {n} tirs pour {p}. C'est lui le plus dangereux.",
        "p_defend": "{p} a déjà récupéré {n} ballons. Quelle lecture du jeu.",
        "p_dribbles": "{p} a déjà éliminé son adversaire {n} fois. Insaisissable.",
        "p_season_goals": "{p} arrivait avec {g} buts cette saison.",
        "p_season_km": "{p} court plus de {km} kilomètres par match cette saison. Il ne s'arrête jamais.",
        "i_welcome": "Bonjour et bienvenue à {venue} ! {home} reçoit {away}.",
        "i_table": "Le {hp} contre le {ap} du classement : un match important.",
        "i_star": "Côté {t}, l'homme à suivre, c'est {p} : déjà {g} buts cette saison.",
        "i_threat": "Pour {t}, attention à {p} : {g} buts.",
        "i_press": "{t} adore presser haut. Si {o} passe ce pressing, il y aura de l'espace.",
        "i_patient": "{t} aime garder le ballon, avec patience. On verra si {o} le laisse faire.",
        "i_ready": "C'est parti !",
    },
}
# Lines that describe the moment itself are said at once; flowing play waits for the cadence.
ORD = {"en": ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth"],
       "es": ["primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "séptimo", "octavo"],
       "fr": ["premier", "deuxième", "troisième", "quatrième", "cinquième", "sixième", "septième", "huitième"]}
_SEASON: dict | None = None


def season() -> dict:
    """The season so far (data/season/season_summary.json, built by secondscreen.dataset)."""
    global _SEASON
    if _SEASON is None:
        import json
        import os
        from pathlib import Path
        p = Path(os.environ.get("SECONDSCREEN_DATA", "data")) / "season" / "season_summary.json"
        try:
            _SEASON = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _SEASON = {}
    return _SEASON


def _num(v: float, lang: str) -> str:
    s = f"{v:.1f}".rstrip("0").rstrip(".")
    return s.replace(".", ",") if lang in ("es", "fr") else s


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
        self.said: dict[str, float] = {}   # colour key (or player+key) -> when it was last said
        self.last_pid: str | None = None

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
            return self._intro(ev)
        if ev.get("player_id") and t in ("pass", "carry", "dribble", "tackle", "interception", "shot"):
            self.last_pid = ev["player_id"]
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

    # ------------------------------------------------------------------ pre-match
    def _intro(self, ev: dict) -> list[dict]:
        """Welcome, the table, who to watch on each side, and the pundit on how it might go."""
        at, ss = ev["elapsed_seconds"], season()
        home, away = ev["home"], ev["away"]
        out = [self._line(at, "i_welcome", {"venue": ev.get("venue", "the ground"), "home": home["name"],
                                            "away": away["name"]}, kind="intro")]
        pos = {r["team_id"]: r["position"] for r in ss.get("standings", [])}
        if home["team_id"] in pos and away["team_id"] in pos:
            hp, ap = pos[home["team_id"]], pos[away["team_id"]]
            out.append(self._line(at, "i_table", {"home": home["short_name"], "away": away["short_name"],
                                                  "hp": lambda lang: ORD[lang][hp - 1].capitalize() if lang == "en" else ORD[lang][hp - 1],
                                                  "ap": lambda lang: ORD[lang][ap - 1]},
                                  kind="intro"))
        players = ss.get("players", {})
        for side, key in ((home, "i_star"), (away, "i_threat")):
            xi = side.get("starting_xi", [])
            star = max(xi, key=lambda p: (players.get(p["player_id"], {}).get("goals", 0), p["position"] in ("ST", "CF")),
                       default=None)
            g = players.get(star["player_id"], {}).get("goals", 0) if star else 0
            if star and g >= 2:
                out.append(self._line(at, key, {"t": side["short_name"], "p": _sur(star["name"]), "g": g,
                                                "formation": side.get("formation", "4-3-3")}, kind="intro"))
        clubs = ss.get("clubs", {})
        presser = next((s for s in (away, home) if clubs.get(s["team_id"], {}).get("block") == "high_press"), None)
        patient = next((s for s in (home, away) if clubs.get(s["team_id"], {}).get("directness", 1) < 0.3), None)
        if presser:
            other = home if presser is away else away
            out.append(self._line(at, "i_press", {"t": presser["short_name"], "o": other["short_name"]}, "pundit", "intro"))
        elif patient:
            other = home if patient is away else away
            out.append(self._line(at, "i_patient", {"t": patient["short_name"], "o": other["short_name"]}, "pundit", "intro"))
        out.append(self._line(at, "i_ready", {}, kind="intro"))
        return out

    # ------------------------------------------------------------------ colour
    def _colour(self, at: float) -> dict | None:
        """In the lulls: alternately a story about the game and one about the player on the ball,
        in everyday football language (no decimals, no analytics jargon)."""
        if not self.engine.home or self.engine.minute < 3:
            return None
        self.colour_turn += 1
        first, second = (self._player_colour, self._team_colour) if self.colour_turn % 2 else \
                        (self._team_colour, self._player_colour)
        return first(at) or second(at)

    def _fresh(self, key: str, at: float, every: float) -> bool:
        if at - self.said.get(key, -1e9) < every:
            return False
        self.said[key] = at
        return True

    def _team_colour(self, at: float) -> dict | None:
        eng = self.engine
        ts, h, a = eng.team_summary(), eng.home, eng.away
        S = lambda tid: self.short.get(tid, tid)  # noqa: E731
        other = lambda tid: a if tid == h else h  # noqa: E731
        for _ in range(5):
            topic = self.colour_turn % 5
            self.colour_turn += 1
            if topic == 0:
                top = max((h, a), key=lambda x: ts[x]["possession_pct"])
                if ts[top]["possession_pct"] >= 55 and self._fresh("c_poss", at, 600):
                    return self._line(at, "c_poss", {"t": S(top), "n": round(ts[top]["possession_pct"])}, "pundit", "colour")
            elif topic == 1:
                top = max((h, a), key=lambda x: ts[x]["shots"])
                if ts[h]["shots"] + ts[a]["shots"] >= 4 and self._fresh("c_shots", at, 600):
                    return self._line(at, "c_shots", {"t": S(top), "a": ts[top]["shots"], "o": S(other(top)),
                                                      "b": ts[other(top)]["shots"]}, "commentator", "colour")
            elif topic == 2 and ts[h]["xg"] + ts[a]["xg"] >= 0.6 and self._fresh("c_chances", at, 900):
                better = h if ts[h]["xg"] > ts[a]["xg"] else a
                if abs(ts[h]["xg"] - ts[a]["xg"]) >= 0.4:
                    return self._line(at, "c_chances", {"t": S(better), "o": S(other(better))}, "pundit", "colour")
                return self._line(at, "c_chances_even", {}, "pundit", "colour")
            elif topic == 3:
                top = max((h, a), key=lambda x: ts[x]["high_turnovers"])
                if ts[top]["high_turnovers"] >= 5 and self._fresh("c_press", at, 900):
                    return self._line(at, "c_press", {"t": S(top)}, "pundit", "colour")
            elif topic == 4 and abs(eng.momentum) >= 40 and self._fresh("c_mom", at, 480):
                return self._line(at, "c_mom", {"t": S(h if eng.momentum > 0 else a)}, "pundit", "colour")
        return None

    def _player_colour(self, at: float) -> dict | None:
        """A fact about the player who just had the ball: today's numbers, or his season."""
        pid = self.last_pid
        ps = self.engine.player(pid) if pid else None
        if ps is None:
            return None
        sp = season().get("players", {}).get(pid, {})
        name = _sur(ps.name)
        options = [
            ("p_passes", ps.passes >= 25 and (ps.pass_completion or 0) >= 0.85, {"n": ps.passes}),
            ("p_km", ps.distance_m >= 6000, {"km": int(ps.distance_m // 1000)}),
            ("p_shots", ps.shots >= 3, {"n": ps.shots}),
            ("p_defend", ps.tackles_won + ps.interceptions >= 5, {"n": ps.tackles_won + ps.interceptions}),
            ("p_dribbles", ps.dribbles >= 3, {"n": ps.dribbles}),
            ("p_season_goals", sp.get("goals", 0) >= 3, {"g": sp.get("goals", 0)}),
            ("p_season_km", sp.get("km_per_match", 0) >= 11, {"km": int(sp.get("km_per_match", 0))}),
        ]
        k = self.colour_turn % len(options)
        for key, ok, fields in options[k:] + options[:k]:
            gap = {"p_season_km": 1500, "p_season_goals": 600}.get(key, 420)   # each kind of fact, any player
            if ok and at - self.said.get(key, -1e9) >= gap and self._fresh(f"{pid}:{key}", at, 1800):
                self.said[key] = at
                role = "pundit" if key in ("p_passes", "p_defend", "p_season_km") else "commentator"
                return self._line(at, key, {"p": name, **fields}, role, "colour")
        return None
