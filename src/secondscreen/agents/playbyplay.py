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
        "name": ["{r}...", "{r}, on the ball", "{r}"],
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
        "pass": "{p} para {r}", "name": "{r}...", "long": "{p}, balón largo para {r}", "box": "{p} la mete al área para {r}",
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
        "pass": "{p} pour {r}", "name": "{r}...", "long": "{p}, ballon long pour {r}", "box": "{p} glisse dans la surface pour {r}",
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
# Context, flow and story phrases (merged into T).
EXTRA = {
    "en": {
        "back_gk": ["{p} back to the keeper", "{p} plays it all the way back to the goalkeeper"],
        "switch": ["{p} switches it out to {r} on the {side}", "{p} spreads it wide to {r}, {side} side"],
        "wing": ["{p} drives down the {side}", "{p} carries it down the {side} flank"],
        "back_build": ["{t} keeping it at the back", "Patient from {t}, knocking it around the back"],
        "mid_build": ["{t} knocking it about in midfield", "{t} probing in the middle of the park"],
        "move": ["Lovely patient move from {t}, {n} passes now", "{t} keeping the ball beautifully, {n} passes in this move"],
        "dribble_n": ["{p} beats his man again, that's {n} today", "{p} skips past another one. {n} take-ons now"],
        "winner": ["{p} wins it back again. He's been everywhere", "and there's {p} again, mopping up"],
        "box_star": ["{p} finds {r} in the box... {g} goals this season, {r}", "{p} picks out {r}, their top scorer, in the area"],
        "booked_foul": "Careful now from {p}, he's already been booked.",
        "booked_tackle": "{p} goes in... and he's on a yellow, remember.",
        "sub_touch": "First touch for {p} since coming on.",
        "danger_fk": "Free kick in a dangerous position for {t}.",
        "keeper_busy": "{k} is having a busy afternoon. That's his {nth} save.",
        "shots_follow": "That's his {nth} shot of the day. He's the one carrying the threat.",
        "fresh_legs": "Fresh legs for {t}: {on} on for {off}, who's run over {km} kilometres.",
        "t15": "Quarter of an hour gone. {state}.", "t30": "Half an hour played. {state}.",
        "t40": "Five minutes to half-time. {state}.", "t60": "An hour gone. {state}.",
        "t75": "Fifteen minutes left. {state}.", "t85": "Five minutes to go. {state}.",
        "stoppage": "We're into stoppage time. {state}.",
        "n_better_level": "{t} have been the better side, but it's still level.",
        "n_better_level_r": "They need to make it count. You don't get this many chances and get away with it.",
        "n_better_behind": "{t} are behind, but they've had the better of it.",
        "n_better_behind_r": "Football can be cruel. They've done everything but score.",
        "n_lead": "{t} look happy to sit on this lead now.",
        "n_lead_r": "Compact and hard to break down. The other lot will have to take some risks.",
        "n_ten": "{t} digging in with ten men.",
        "n_ten_r": "Every one of them is putting a shift in. They'll be out on their feet by the end.",
        "n_chaos": "It's end to end now!",
        "n_chaos_r": "Neither side's in control. The next goal could come at either end.",
        "n_cagey": "It's been cagey so far.",
        "n_cagey_r": "Both sides feeling each other out. Nobody wants to make the first mistake.",
        "n_need": "Time's running out for {t}.",
        "n_need_r": "They have to throw bodies forward now. Nothing to lose.",
        "n_control": "{t} are in complete control here.",
        "n_control_r": "They're not letting the other lot have a sniff of the ball.",
        "left": "left", "right": "right",
    },
    "es": {
        "back_gk": "{p} atrás, para el portero", "switch": "{p} cambia de orientación hacia {r}, por la {side}",
        "wing": "{p} conduce por la banda {side}", "back_build": "{t} toca atrás, sin prisa",
        "mid_build": "{t} mueve el balón en el centro del campo", "move": "Qué paciencia de {t}: ya van {n} pases",
        "dribble_n": "{p} vuelve a irse de su marca: ya van {n}", "winner": "{p} recupera otra vez. Está en todas partes",
        "box_star": "{p} encuentra a {r} en el área... {g} goles esta temporada",
        "booked_foul": "Cuidado {p}, que ya tiene amarilla.", "booked_tackle": "{p} entra fuerte... y tiene amarilla.",
        "sub_touch": "Primer balón para {p} desde que entró.", "danger_fk": "Falta peligrosa para {t}.",
        "keeper_busy": "Tarde ajetreada para {k}: es su {nth} parada.",
        "shots_follow": "Es el {nth} tiro de {p} hoy. Es el más peligroso.",
        "fresh_legs": "Piernas frescas en {t}: entra {on} por {off}, que ha corrido más de {km} kilómetros.",
        "t15": "Un cuarto de hora. {state}.", "t30": "Media hora de juego. {state}.",
        "t40": "Cinco minutos para el descanso. {state}.", "t60": "Una hora de partido. {state}.",
        "t75": "Quedan quince minutos. {state}.", "t85": "Cinco minutos para el final. {state}.",
        "stoppage": "Entramos en el tiempo añadido. {state}.",
        "n_better_level": "{t} ha sido mejor, pero sigue el empate.",
        "n_better_level_r": "Tiene que aprovecharlo. No puedes perdonar tantas ocasiones.",
        "n_better_behind": "{t} va perdiendo, pero ha sido mejor.", "n_better_behind_r": "El fútbol es cruel. Lo ha hecho todo menos marcar.",
        "n_lead": "{t} parece cómodo defendiendo la ventaja.", "n_lead_r": "Bien juntos, difíciles de romper. El rival tendrá que arriesgar.",
        "n_ten": "{t} resiste con diez.", "n_ten_r": "Todos se dejan el alma. Acabarán agotados.",
        "n_chaos": "¡Ahora es un ida y vuelta!", "n_chaos_r": "Nadie controla el partido. El próximo gol puede caer en cualquier área.",
        "n_cagey": "Partido de mucho respeto.", "n_cagey_r": "Los dos se estudian. Nadie quiere cometer el primer error.",
        "n_need": "Se le acaba el tiempo a {t}.", "n_need_r": "Tiene que volcarse. No tiene nada que perder.",
        "n_control": "{t} tiene el control total.", "n_control_r": "No le deja ni oler el balón al rival.",
        "left": "izquierda", "right": "derecha",
    },
    "fr": {
        "back_gk": "{p} en retrait pour le gardien", "switch": "{p} renverse le jeu vers {r}, côté {side}",
        "wing": "{p} file sur le côté {side}", "back_build": "{t} fait tourner derrière",
        "mid_build": "{t} fait circuler au milieu", "move": "Belle patience de {t} : {n} passes déjà",
        "dribble_n": "{p} élimine encore son adversaire : {n} dribbles réussis", "winner": "{p} récupère encore. Il est partout",
        "box_star": "{p} trouve {r} dans la surface... {g} buts cette saison",
        "booked_foul": "Attention pour {p}, il est déjà averti.", "booked_tackle": "{p} s'engage... et il est déjà averti.",
        "sub_touch": "Premier ballon pour {p} depuis son entrée.", "danger_fk": "Coup franc dangereux pour {t}.",
        "keeper_busy": "{k} est très sollicité : c'est son {nth} arrêt.",
        "shots_follow": "C'est le {nth} tir de {p} aujourd'hui. C'est lui le plus dangereux.",
        "fresh_legs": "Du sang neuf pour {t} : {on} remplace {off}, qui a couru plus de {km} kilomètres.",
        "t15": "Un quart d'heure de jeu. {state}.", "t30": "Une demi-heure de jeu. {state}.",
        "t40": "Cinq minutes avant la pause. {state}.", "t60": "Une heure de jeu. {state}.",
        "t75": "Encore quinze minutes. {state}.", "t85": "Cinq minutes à jouer. {state}.",
        "stoppage": "Nous entrons dans le temps additionnel. {state}.",
        "n_better_level": "{t} a été meilleur, mais c'est toujours l'égalité.",
        "n_better_level_r": "Il faut concrétiser. On ne peut pas gâcher autant d'occasions.",
        "n_better_behind": "{t} est mené, mais a été meilleur.", "n_better_behind_r": "Le football est cruel. Ils ont tout fait sauf marquer.",
        "n_lead": "{t} semble se contenter de cet avantage.", "n_lead_r": "Compact, difficile à manœuvrer. L'adversaire va devoir prendre des risques.",
        "n_ten": "{t} résiste à dix.", "n_ten_r": "Tout le monde se sacrifie. Ils vont finir sur les rotules.",
        "n_chaos": "Ça va d'un but à l'autre maintenant !", "n_chaos_r": "Personne ne contrôle. Le prochain but peut tomber des deux côtés.",
        "n_cagey": "Un début de match fermé.", "n_cagey_r": "Les deux équipes s'observent. Personne ne veut faire la première erreur.",
        "n_need": "Le temps presse pour {t}.", "n_need_r": "Ils doivent tout tenter maintenant. Rien à perdre.",
        "n_control": "{t} maîtrise complètement le match.", "n_control_r": "L'adversaire ne voit pas le ballon.",
        "left": "gauche", "right": "droit",
    },
}
ORDN = {"en": ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"],
        "es": ["primera", "segunda", "tercera", "cuarta", "quinta", "sexta", "séptima", "octava", "novena", "décima"],
        "fr": ["premier", "deuxième", "troisième", "quatrième", "cinquième", "sixième", "septième", "huitième", "neuvième", "dixième"]}
ORDN_M = {"es": ["primer", "segundo", "tercer", "cuarto", "quinto", "sexto", "séptimo", "octavo", "noveno", "décimo"]}
for _lang, _extra in EXTRA.items():
    T[_lang].update(_extra)

# Lines the viewer must not miss: the box says them at the next gap rather than skipping them.
MUST_SAY = {"yellow", "sub", "fresh_legs", "corner", "danger_fk", "booked_foul", "booked_tackle", "keeper_busy",
            "ko1", "ko2", "ht", "ft", "t15", "t30", "t40", "t60", "t75", "t85", "stoppage"}

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
        self.positions: dict[str, str] = {}
        self.booked: set[str] = set()
        self.fresh_subs: set[str] = set()
        self.saves: dict[str, int] = {}
        self.move: tuple[str | None, int] = (None, 0)    # (team, completed passes in a row)
        self.marks_said: set[str] = set()

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
            f = {k: (v(lang) if callable(v) else v) for k, v in fields.items() if not k.startswith("_")}
            tpl = T[lang][key]
            tpl = tpl[self.n % len(tpl)] if isinstance(tpl, list) else tpl
            s = tpl.format(**f)
            text[lang] = s[0].upper() + s[1:] if s else s
        line = {"at": at, "role": role, "kind": kind, "key": key, "text": text}
        if key in MUST_SAY:
            line["priority"] = True       # waits for a gap rather than being skipped
        return line

    # ------------------------------------------------------------------ feed
    def feed(self, ev: dict) -> list[dict]:
        """Call after the engine has ingested `ev`. Returns lines to schedule (usually none or one)."""
        t, at = ev["type"], ev["elapsed_seconds"]
        team, pid, p = ev.get("team_id"), ev.get("player_id"), _sur(ev.get("player_name"))
        out: list[dict] = []

        if t == "match_start":
            self.short = {ev["home"]["team_id"]: ev["home"]["short_name"], ev["away"]["team_id"]: ev["away"]["short_name"]}
            self.positions = {q["player_id"]: q["position"] for side in ("home", "away")
                              for q in ev[side]["starting_xi"] + ev[side]["bench"]}
            return self._intro(ev)
        if pid and t in ("pass", "carry", "dribble", "tackle", "interception", "shot"):
            self.last_pid = pid
            if pid in self.fresh_subs:                         # a substitute's first touch
                self.fresh_subs.discard(pid)
                out.append(self._mark(at, self._line(at, "sub_touch", {"p": p})))
        if t == "period_start":
            self.move = (None, 0)
            return [self._mark(at, self._line(at, "ko1" if ev["period"] == 1 else "ko2", {}))]
        if t in ("period_end", "match_end"):
            if t == "period_end" and ev["period"] == 2:
                return out
            key = "ht" if t == "period_end" else "ft"
            return [self._mark(at, self._line(at, key, {"state": self._state}))]
        clock_line = self._clock_marker(ev, at)
        if clock_line:
            return out + [self._mark(at, clock_line)]

        tname = self.short.get(team, team)
        if t == "pass":
            r, rid = _sur(ev.get("recipient_name")), ev.get("recipient_id")
            x0, y0 = self._rel(team, ev.get("x"), ev.get("y"))
            x1, y1 = self._rel(team, ev.get("end_x"), ev.get("end_y"))
            if ev.get("outcome") != "complete":
                self.buf.append(("lost", {"p": p}))
                self.move = (None, 0)
            else:
                mt, mn = self.move
                self.move = (team, mn + 1) if mt == team else (team, 1)
                rgoals = season().get("players", {}).get(rid, {}).get("goals", 0)
                if self.positions.get(rid) == "GK":
                    self.buf.append(("back_gk", {"p": p}))
                elif x1 >= metrics.BOX_X and abs(y1 - 34) < 20:
                    if rgoals >= 4 and self._fresh(f"{rid}:box_star", at, 900):
                        self.buf.append(("box_star", {"p": p, "r": r, "g": rgoals}))
                    else:
                        self.buf.append(("box", {"p": p, "r": r}))
                elif abs(y1 - y0) >= 28 and (ev.get("distance_m") or 0) >= 25:
                    self.buf.append(("switch", {"p": p, "r": r, "side": self._side(y1)}))
                elif (ev.get("distance_m") or 0) >= 30:
                    self.buf.append(("long", {"p": p, "r": r}))
                elif x0 < 70 <= x1:
                    self.buf.append(("third", {"p": p, "r": r}))
                else:
                    self.buf.append(("pass", {"p": p, "r": r, "_x": x1}))
        elif t == "carry":
            x0, _ = self._rel(team, ev.get("x"), ev.get("y"))
            x1, y1 = self._rel(team, ev.get("end_x"), ev.get("end_y"))
            if x1 - x0 >= 10:
                self.buf.append(("wing", {"p": p, "side": self._side(y1)}) if (y1 < 16 or y1 > 52) else ("carry", {"p": p}))
        elif t == "dribble":
            ps = self.engine.player(pid)
            if ev.get("outcome") == "success" and ps and ps.dribbles >= 3 and self._fresh(f"{pid}:dribble_n", at, 600):
                self.buf.append(("dribble_n", {"p": p, "n": ps.dribbles}))
            else:
                self.buf.append(("dribble" if ev.get("outcome") == "success" else "dribble_fail", {"p": p}))
        elif t in ("tackle", "interception"):
            self.move = (None, 0)
            if t == "tackle" and ev.get("outcome") != "won":
                pass
            elif pid in self.booked and t == "tackle" and self._fresh(f"{pid}:booked_tackle", at, 600):
                return out + [self._mark(at, self._line(at, "booked_tackle", {"p": p}))]
            else:
                ps = self.engine.player(pid)
                won = (ps.tackles_won + ps.interceptions) if ps else 0
                if won >= 6 and self._fresh(f"{pid}:winner", at, 600):
                    self.buf.append(("winner", {"p": p}))
                else:
                    self.buf.append(("tackle" if t == "tackle" else "intercept", {"p": p}))
        elif t == "clearance":
            self.buf.append(("clear", {"p": p}))
            self.move = (None, 0)
        elif t == "shot" and ev.get("outcome") != "goal":
            x, y = self._rel(team, ev.get("x"), ev.get("y"))
            xg = metrics.expected_goals(x, y, ev.get("body_part", "foot"), ev.get("situation", "open_play"))
            self.buf.clear()
            self.move = (None, 0)
            if xg < BIG_XG:                                     # big chances are the spotter's
                key = {"saved": "shot_saved", "blocked": "shot_blocked", "post": "shot_post"}.get(ev.get("outcome"), "shot_wide")
                line = self._line(at, key, {"p": p})
                ps = self.engine.player(pid)
                if ps and ps.shots >= 3 and self._fresh(f"{pid}:shots", at, 900):
                    line["follow"] = self._line(at, "shots_follow", {"p": p, "nth": self._nth(ps.shots, male=True)}, "pundit")
                out.append(self._mark(at, line))
            return out
        elif t == "save":
            self.saves[pid] = self.saves.get(pid, 0) + 1
            n = self.saves[pid]
            if n >= 3 and self._fresh(f"{pid}:busy", at, 900):
                return out + [self._mark(at, self._line(at, "keeper_busy", {"k": p, "nth": self._nth(n)}))]
            return out
        elif t == "foul":
            self.move = (None, 0)
            if pid in self.booked:
                return out + [self._mark(at, self._line(at, "booked_foul", {"p": p}))]
            fouled = self.engine.opp(team) if self.engine.home else team
            fx, _ = self._rel(fouled, ev.get("x"), ev.get("y"))
            if fx >= 72:
                return out + [self._mark(at, self._line(at, "danger_fk", {"t": self.short.get(fouled, fouled)}))]
            return out + [self._mark(at, self._line(at, "foul", {"p": p}))]
        elif t == "card" and ev.get("card") == "yellow":
            self.booked.add(pid)
            return out + [self._mark(at, self._line(at, "yellow", {"p": p}))]
        elif t == "corner":
            return out + [self._mark(at, self._line(at, "corner", {"t": tname}))]
        elif t == "substitution":
            self.fresh_subs.add(pid)
            off = self.engine.player(ev.get("player_off_id"))
            km = int(off.distance_m // 1000) if off else 0
            key = "fresh_legs" if km >= 5 else "sub"
            return out + [self._mark(at, self._line(at, key, {"t": tname, "on": p, "off": _sur(ev.get("player_off_name")),
                                                             "km": km}))]
        elif t == "goal":
            self.buf.clear()
            self.move = (None, 0)
            self.last_at = at + 8          # the call and the celebration own the next few seconds
            return out

        if self.buf and at - self.last_at >= GAP:
            self.n += 1
            line = self._colour(at) if self.n % COLOUR_EVERY == 0 else None
            out.append(self._mark(at, line or self._flow(at)))
        return out

    # ------------------------------------------------------------------ context helpers
    def _rel(self, team: str | None, x: float | None, y: float | None) -> tuple[float, float]:
        if team is None or x is None or not self.engine.home:
            return (x or 0.0, y if y is not None else 34.0)
        y = 34.0 if y is None else y
        return (self.engine.ax(team, x), y if team == self.engine.home else metrics.PITCH_Y - y)

    @staticmethod
    def _side(y_rel: float):
        """Which flank, for a team attacking left to right (their right back plays at low y)."""
        return (lambda lang: T[lang]["left"]) if y_rel > 34 else (lambda lang: T[lang]["right"])

    @staticmethod
    def _nth(n: int, male: bool = False):
        def word(lang: str) -> str:
            table = (ORDN_M.get(lang) if male else None) or ORDN[lang]
            return table[n - 1] if 1 <= n <= len(table) else str(n)
        return word

    def _clock_marker(self, ev: dict, at: float) -> dict | None:
        """Quarter of an hour, half an hour... and stoppage time, said once each, with the score."""
        secs, period = ev.get("clock_seconds", 0), ev.get("period", 1)
        marks = [("t15", 1, 900), ("t30", 1, 1800), ("t40", 1, 2400), ("t60", 2, 3600), ("t75", 2, 4500),
                 ("t85", 2, 5100), ("stoppage1", 1, 2700), ("stoppage2", 2, 5400)]
        for key, per, sec in marks:
            if period == per and secs >= sec and key not in self.marks_said and at - self.last_at >= 2:
                self.marks_said.add(key)
                line = self._line(at, "stoppage" if key.startswith("stoppage") else key, {"state": self._state})
                if key in ("t75", "t85", "stoppage2", "t30", "t60"):
                    story = self._narrative(at, force=True)
                    if story:
                        line["follow"] = story
                return line
        return None

    def _narrative(self, at: float, force: bool = False) -> dict | None:
        """The story of the game, as an exchange: the commentator sets it up, the pundit answers."""
        eng = self.engine
        if not eng.home or eng.minute < 8:
            return None
        h, a = eng.home, eng.away
        ts = eng.team_summary()
        sc = eng.score
        S = lambda tid: self.short.get(tid, tid)  # noqa: E731
        lead = h if sc[h] > sc[a] else a if sc[a] > sc[h] else None
        trail = (a if lead == h else h) if lead else None
        better = h if ts[h]["xg"] - ts[a]["xg"] >= 0.8 else a if ts[a]["xg"] - ts[h]["xg"] >= 0.8 else None
        regime = eng.regime or ""
        options = []
        if trail and eng.period == 2 and eng.minute >= 80:
            options.append(("n_need", trail))
        short = [tm for tm in (h, a) if ts[tm]["players_on_pitch"] < 11]
        if short and (lead in short or lead is None):
            options.append(("n_ten", short[0]))
        if better and lead is None:
            options.append(("n_better_level", better))
        if better and trail == better:
            options.append(("n_better_behind", better))
        if regime == "chaos":
            options.append(("n_chaos", None))
        if regime.startswith("control:"):
            ctl = regime.split(":", 1)[1]
            if (eng.momentum > 15 and ctl == h) or (eng.momentum < -15 and ctl == a):   # only when it agrees
                options.append(("n_control", ctl))
        if lead and eng.period == 2 and eng.minute >= 60:
            options.append(("n_lead", lead))
        if eng.minute < 25 and ts[h]["shots"] + ts[a]["shots"] <= 2:
            options.append(("n_cagey", None))
        for key, tm in options:
            if self._fresh(key, at, 600 if force else 900):
                line = self._line(at, key, {"t": S(tm)} if tm else {}, "commentator", "story")
                line["follow"] = self._line(at, key + "_r", {}, "pundit", "story")
                return line
        return None

    def _mark(self, at: float, line: dict) -> dict:
        self.last_at = at
        self.buf.clear()
        return line

    def _flow(self, at: float) -> dict:
        """Describe the latest passage of play: a long move, a phase of build-up, the last couple of
        actions, or a chain of names."""
        mt, mn = self.move
        if mt and mn >= 8 and mn // 4 > self.said.get(f"move:{mt}:{int(at // 600)}", 0):
            self.said[f"move:{mt}:{int(at // 600)}"] = mn // 4
            return self._line(at, "move", {"t": self.short.get(mt, mt), "n": mn})
        recent = self.buf[-3:]
        if mt and len(recent) == 3 and all(k == "pass" for k, _ in recent) and self.n % 3 == 0:
            xs = [f.get("_x", 50) for _, f in recent]
            phase = "back_build" if max(xs) < 38 else "mid_build" if max(xs) < 68 else None
            if phase:
                return self._line(at, phase, {"t": self.short.get(mt, mt)})
        if len(recent) == 3 and all(k == "pass" for k, _ in recent):
            names = [recent[0][1]["p"], recent[1][1]["p"], recent[2][1]["p"], recent[2][1]["r"]]
            a, b, c = names[1], names[2], names[3]
            if len({a, b, c}) == 3:
                return self._line(at, "chain", {"a": a, "b": b, "c": c})
        key, fields = recent[-1]
        # Plain passes: mostly just the name on the ball, the way commentators follow play.
        if key == "pass" and self.n % 3 != 0:
            return self._line(at, "name", fields)
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
        order = [self._narrative, self._team_colour, self._player_colour]
        k = self.colour_turn % 3
        for fn in order[k:] + order[:k]:
            line = fn(at)
            if line:
                return line
        return None

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
