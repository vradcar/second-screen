"""Spoken commentary: a play-by-play commentator and a co-commentator, in the style of
English top-flight TV football, written per language for each big moment.

The Commentator agent writes four parts per language:
    build   the climb towards the moment ("Fallow whips it in... Quarry rises...")
    peak    the call ("And he's headed it in!")
    after   who, and what it means ("Quarry! Level at 1-1.")
    pundit  the co-commentator's calmer read ("There was nothing on there. What a finish.")
Everything is said the way people talk about football: no xG figures, decimals or analytics terms.
Each line goes through the same grounding rules as every other agent output: numbers must
come from FACTS and names from the roster. A line that fails is replaced by a template
written in the same style, so commentary never says something the stats engine can't back.

Batch mode, for a recorded run (writes data/match_<id>.commentary.jsonl):
    python -m secondscreen.agents.commentary data/match_SS00076 --mode mock     # templates
    python -m secondscreen.agents.commentary data/match_SS00076 --mode record   # Foundry model
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import zlib
from pathlib import Path
from typing import Any

from agent_framework import Executor, WorkflowContext, handler

from secondscreen.agents.factcheck import _global_allowed, number_ok, numbers_in, unknown_names
from secondscreen.agents.schemas import Commentary, CommentaryLine, MomentDraft, PublishedMoment, RenderedMoment

SPOKEN = {"goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "late_surge", "hot_streak",
          "fatigue_fade", "pressing_spell"}
LIMITS = {"build": 30, "peak": 8, "after": 35, "pundit": 45}   # words


# ---------------------------------------------------------------- templates
def _f(facts: dict, key: str, default: Any = None) -> Any:
    return facts.get(f"signal.{key}", default)


def _num(v: float, lang: str, nd: int = 2) -> str:
    s = f"{round(v, nd):g}"
    return s.replace(".", ",") if lang in ("es", "fr") else s


def _state(facts: dict, lang: str) -> str:
    """Who leads, from the score facts, in each language."""
    teams = {k.split(".")[1]: v for k, v in facts.items() if k.startswith("team.") and k.endswith(".name")}
    score = {t: facts.get(f"match.score.{t}", 0) for t in teams}
    if len(score) != 2:
        return facts.get("match.state", "")
    (a, ga), (b, gb) = sorted(score.items(), key=lambda kv: -kv[1])
    if ga == gb:
        return {"en": f"Level at {ga}-{gb}", "es": f"Empate a {ga}", "fr": f"Égalité, {ga}-{gb}"}[lang]
    lead = teams[a]
    return {"en": f"{lead} lead {ga}-{gb}", "es": f"{lead} gana {ga}-{gb}", "fr": f"{lead} mène {ga}-{gb}"}[lang]


def template_line(kind: str, facts: dict, lang: str, fallback_text: str = "", turn: int | None = None) -> CommentaryLine:
    """Template commentary. `turn` (how many of this kind came before) rotates the wording."""
    lang = lang if lang in ("en", "es", "fr") else "en"
    L = lambda en, es, fr: {"en": en, "es": es, "fr": fr}[lang]  # noqa: E731
    if turn is None:
        turn = zlib.crc32(str(facts.get("match.clock", "")).encode())
    V = lambda *opts: L(*opts[turn % len(opts)])  # noqa: E731 - vary repeated calls, deterministically
    team = facts.get("signal.team", "")
    build = peak = after = pundit = ""
    used: list[str] = ["match.state"]

    if kind == "goal":
        scorer, assist = _f(facts, "scorer", ""), _f(facts, "assist")
        head = _f(facts, "shot.body_part") == "head"
        sit = _f(facts, "shot.situation", "")
        xg = _f(facts, "shot.xg")
        if sit == "penalty":
            build = L(f"{scorer} steps up... runs in...", f"{scorer} ante el balón... carrerilla...",
                      f"{scorer} face au gardien... il s'élance...")
        elif head and assist:
            build = L(f"{assist} whips it in... {scorer} rises...", f"Centro de {assist}... se eleva {scorer}...",
                      f"Centre de {assist}... {scorer} s'élève...")
        elif head:
            build = L(f"Ball into the box... {scorer} rises...", f"Balón al área... se eleva {scorer}...",
                      f"Ballon dans la surface... {scorer} s'élève...")
        elif sit == "counter":
            build = L(f"{team} break at pace... {scorer}...", f"Contragolpe de {team}... {scorer}...",
                      f"{team} en contre... {scorer}...")
        elif assist:
            build = L(f"{assist}... finds {scorer}... shoots!", f"{assist}... para {scorer}... ¡dispara!",
                      f"{assist}... pour {scorer}... il frappe !")
        else:
            build = L(f"{team} work it forward... {scorer}... shoots!", f"Avanza {team}... {scorer}... ¡dispara!",
                      f"{team} s'approche... {scorer}... il frappe !")
        goals_today = _f(facts, "scorer_goals_today", 1)
        if goals_today >= 3:
            peak = L("Hat-trick! He's done it!", "¡Triplete! ¡Gooool!", "Triplé ! Buuut !")
        elif head:
            peak = L("And he's headed it in!", "¡Gooool de cabeza!", "Buuut de la tête !")
        else:
            peak = L("And it's in!", "¡Gooool!", "Buuuut !")
        after = L(f"{scorer}! ", f"¡{scorer}! ", f"{scorer} ! ") + f"{_state(facts, lang)}."
        if _f(facts, "comeback_complete"):
            after += L(" What a turnaround!", " ¡Qué remontada!", " Quel retournement !")
        elif facts.get("match.minute", 0) >= 85 and _f(facts, "game_state") in ("go_ahead", "equaliser"):
            after += L(" Late, late drama!", " ¡Drama en el descuento!", " Un final de folie !")
        if _f(facts, "comeback_complete"):
            pundit = L("They were behind and they've turned it around. That's character.",
                       "Iban perdiendo y le han dado la vuelta. Eso es carácter.",
                       "Ils étaient menés et ils ont renversé la situation. Quel caractère.")
        elif xg is not None and xg < 0.15:
            pundit = V(("There was nothing on there! He's made that out of absolutely nothing.",
                        "¡No había nada ahí! Se ha sacado ese gol de la nada.",
                        "Il n'y avait rien ! Il a fait ce but à partir de rien."),
                       ("Look at the angle he's had to find there. That is a top-class finish.",
                        "Mira el ángulo que ha encontrado. Una definición de primer nivel.",
                        "Regardez l'angle qu'il a trouvé. Une finition de très haut niveau."))
            used.append("signal.shot.xg")
        elif xg is not None and xg >= 0.4:
            pundit = V(("Great chance, and he makes no mistake. The build-up did all the hard work there.",
                        "Ocasión clarísima y no perdona. La jugada previa hizo todo el trabajo.",
                        "Grosse occasion, et il ne tremble pas. Toute la construction a fait le travail."),
                       ("You have to take those, and he does. Composed as you like.",
                        "Esas hay que meterlas, y la mete. Con una tranquilidad tremenda.",
                        "Celles-là, il faut les mettre, et il la met. Avec un calme olympien."))
            used.append("signal.shot.xg")
        else:
            pundit = L("Good movement, and a composed finish when it mattered.",
                       "Buen desmarque y una definición serena.", "Bon appel, et une finition pleine de sang-froid.")
        used += ["signal.scorer", "signal.game_state"]

    elif kind == "red_card":
        player, left = _f(facts, "player", ""), _f(facts, "players_left", 10)
        mins = facts.get("match.minutes_remaining")
        second = _f(facts, "reason") == "second yellow"
        build = L("The referee's reaching for his pocket...", "El árbitro se lleva la mano al bolsillo...",
                  "L'arbitre met la main à la poche...")
        peak = (L("Second yellow, and he's off!", "¡Segunda amarilla, expulsado!", "Deuxième jaune, il est exclu !")
                if second else L("Straight red! He's off!", "¡Roja directa!", "Carton rouge direct !"))
        after = L(f"{player} has to go, and {team} are down to {left}.", f"{player} a la calle, {team} se queda con {left}.",
                  f"{player} doit sortir, {team} est réduit à {left}.")
        if mins:
            pundit = L(f"{mins} minutes left, plus stoppage time, with a man short. That's a long afternoon.",
                       f"Quedan {mins} minutos con uno menos. Se les va a hacer eterno.",
                       f"Encore {mins} minutes à jouer en infériorité. Ça va être long.")
            used.append("match.minutes_remaining")
        used += ["signal.player", "signal.players_left", "signal.reason"]

    elif kind in ("big_chance_missed", "big_save"):
        player, kp, outcome, xg = _f(facts, "player", ""), _f(facts, "key_passer"), _f(facts, "outcome", ""), _f(facts, "xg")
        build = (L(f"{kp} picks him out... {player}...", f"{kp} la pone... {player}...", f"{kp} le trouve... {player}...")
                 if kp else L(f"{player}, in on goal...", f"{player}, solo ante el portero...", f"{player} seul face au but..."))
        peak = {"saved": V(("What a save!", "¡Qué parada!", "Quel arrêt !"),
                           ("Oh, brilliant save!", "¡Paradón!", "Superbe parade !")),
                "blocked": V(("Blocked! Somebody's got in the way!", "¡Bloqueado!", "Contré !"),
                             ("Charged down!", "¡Lo tapan!", "Contré au dernier moment !"),
                             ("Thrown bodies in the way!", "¡Se tiran al suelo y lo bloquean!", "Ils se jettent devant !")),
                "post": L("Off the post!", "¡Al palo!", "Sur le poteau !")}.get(
                    outcome, V(("Oh, he's missed it!", "¡Increíble, la manda fuera!", "Oh, il l'a manqué !"),
                               ("Wide! Oh, that's a big one!", "¡Fuera por poco!", "À côté ! Quelle occasion !")))
        after = (L(f"Brilliant from the keeper. {player} can't believe it.", f"Paradón. {player} no se lo puede creer.",
                   f"Superbe parade. {player} n'en revient pas.") if outcome == "saved"
                 else V(("How has that not gone in?", "¿Cómo no ha entrado eso?", "Comment ça n'est pas rentré ?"),
                        (f"{player} has his head in his hands.", f"{player} se lleva las manos a la cabeza.",
                         f"{player} se prend la tête dans les mains."),
                        (f"That's a let-off for the defence, and {player} knows it.", "Se salva la defensa.",
                         "La défense s'en sort bien.")))
        if xg is not None:
            pundit = (V(("He has to score there. Honestly, that's as good a chance as you'll get all day.",
                         "Tenía que ser gol. Es la ocasión más clara que vas a ver en todo el partido.",
                         "Il doit marquer. C'est la plus belle occasion qu'on verra de tout le match."),
                        ("He'll be seeing that one in his sleep tonight. Wide open.",
                         "Esa la va a soñar esta noche. Estaba solo.",
                         "Il va en rêver cette nuit. Il était tout seul.")) if xg >= 0.5 else
                      V(("Good opening, that. He'll feel he should at least have hit the target.",
                         "Buena ocasión. Debió al menos tirar a puerta.",
                         "Belle occasion. Il devait au moins cadrer."),
                        ("Half a yard more space and that's a goal. So close.",
                         "Medio metro más de espacio y es gol. Qué cerca.",
                         "Un demi-mètre de plus et c'est but. Si près.")))
            used.append("signal.xg")
        used += ["signal.player", "signal.outcome"]

    elif kind == "penalty_awarded":
        taker = _f(facts, "taker", "")
        build = L("He's gone down in the box...", "Cae dentro del área...", "Il tombe dans la surface...")
        peak = L("Penalty!", "¡Penalti!", "Penalty !")
        after = L("The referee points to the spot.", "El árbitro señala el punto de penalti.",
                  "L'arbitre désigne le point de penalty.")
        if taker:
            pundit = L(f"Big moment. {taker} will fancy this.", f"Momento clave. {taker} tiene la responsabilidad.",
                       f"Moment clé. {taker} prend ses responsabilités.")

    elif kind == "pressing_spell":
        n = _f(facts, "press_actions_last_6")
        peak = V(("Here they come again!", "¡Otra vez arriba!", "Ils remettent le pressing !"),
                 ("They're hunting in packs!", "¡Presión en bloque!", "Ils chassent en meute !"),
                 ("No time on the ball here!", "¡No dejan pensar!", "Pas une seconde de répit !"))
        after = V((f"{team} are swarming all over the ball.", f"{team} asfixia la salida rival.",
                   f"{team} étouffe la relance adverse."),
                  (f"{team} pressing right up the pitch.", f"{team} presiona muy arriba.", f"{team} presse très haut."),
                  (f"{team} won't let them play out from the back.", f"{team} no deja salir jugando al rival.",
                   f"{team} empêche toute relance propre."))
        if n:
            pundit = L("They're not giving them a second on the ball. Every pass, there's someone right on top of them.",
                       "No les dejan ni respirar. En cada pase hay alguien encima.",
                       "Ils ne laissent aucun répit. À chaque passe, quelqu'un est déjà sur le porteur.")
            used.append("signal.press_actions_last_6")

    elif kind == "late_surge":
        n = _f(facts, "box_entries_last_8")
        peak = L("They're throwing everything at it now!", "¡Todo al ataque!", "Ils poussent tous !")
        after = L(f"{team} pinning them back in the closing minutes.", f"{team} encierra a su rival en el tramo final.",
                  f"{team} pousse dans les dernières minutes.")
        if n:
            pundit = L("They're in the box again and again now. Something has to give.",
                       "Llegan al área una y otra vez. Algo tiene que pasar.",
                       "Ils arrivent dans la surface encore et encore. Ça va finir par céder.")
            used.append("signal.box_entries_last_8")

    elif kind == "hot_streak":
        player, n = _f(facts, "player", ""), _f(facts, "touches_last_12")
        peak = L("He's everywhere!", "¡Está en todas partes!", "Il est partout !")
        after = L(f"{player} wants the ball every time.", f"{player} pide el balón en cada jugada.",
                  f"{player} réclame tous les ballons.")
        if n:
            pundit = L("Everything is going through him at the moment. He wants it every single time.",
                       "Ahora mismo todo pasa por él. La pide en cada jugada.",
                       "Tout passe par lui en ce moment. Il le demande à chaque fois.")
            used.append("signal.touches_last_12")

    elif kind == "fatigue_fade":
        pc = _f(facts, "pass_completion_last_10")
        peak = L("Legs are going now.", "Ya no hay piernas.", "Les jambes sont lourdes.")
        after = L(f"{team} are starting to tire.", f"{team} empieza a acusar el cansancio.", f"{team} commence à fatiguer.")
        if pc:
            pct = round(pc * 100)
            pundit = L("You can see it. Passes that were finding a teammate half an hour ago are going astray now.",
                       "Se nota. Pases que antes llegaban ahora se pierden.",
                       "Ça se voit. Les passes qui trouvaient un partenaire il y a une demi-heure se perdent maintenant.")
            used.append("signal.pass_completion_last_10")
    else:
        after = fallback_text

    return CommentaryLine(lang=lang, build=build, peak=peak, after=after, pundit=pundit, facts=used)


# ------------------------------------------------------------------ checking
# Spoken commentary is for viewers, not analysts: no metrics jargon, no decimals.
JARGON = re.compile(r"\bxG\b|expected goals|goles esperados|buts attendus|\bPPDA\b|momentum score|press(ing)? actions|"
                    r"\bregime\b|\d+[.,]\d+", re.I)


def check_line(line: CommentaryLine, context: dict, lang: str) -> list[str]:
    issues = []
    spoken = " ".join((line.build, line.peak, line.after, line.pundit))
    if m := JARGON.search(spoken):
        issues.append(f"say it in football language, not '{m.group(0)}'")
    if line.lang != lang:
        issues.append(f"expected language {lang}, got {line.lang}")
    for part, limit in LIMITS.items():
        if len(getattr(line, part).split()) > limit:
            issues.append(f"{part} is longer than {limit} words")
    text = " ".join((line.build, line.peak, line.after, line.pundit))
    allowed = _global_allowed(context)
    for n in numbers_in(text):
        if not number_ok(n, allowed):
            issues.append(f"number {n:g} not in facts")
    for name in unknown_names(text, set(context["roster"])):
        issues.append(f"unknown player '{name}'")
    return issues


def langs_for(personas) -> list[str]:
    out: list[str] = []
    for p in personas:
        if p.lang not in out:
            out.append(p.lang)
    return out


async def write_commentary(agent, kind: str, draft: MomentDraft, context: dict, langs: list[str],
                           strap: dict[str, str] | None = None, turn: int | None = None) -> tuple[dict, list[dict]]:
    """{lang: line + source} and a check log. Never raises: the template is the floor."""
    from secondscreen.agents.pipeline import _value, payload_block
    log: list[dict] = []
    lines: dict[str, CommentaryLine] = {}
    if agent is not None:
        try:
            resp = await agent.run("Write the commentary.\n" + payload_block({
                "kind": kind, "moment": draft.model_dump(), "facts": context["facts"], "langs": langs, "turn": turn}),
                options={"response_format": Commentary, "temperature": 0.8})
            for ln in _value(resp, Commentary).lines:
                if ln.lang in langs and ln.lang not in lines:
                    problems = check_line(ln, context, ln.lang)
                    if problems:
                        log.append({"step": "commentary_check", "lang": ln.lang, "rejected": problems})
                    else:
                        lines[ln.lang] = ln
        except Exception as e:  # noqa: BLE001
            log.append({"step": "commentary", "error": repr(e)[:300]})
    out = {}
    for lang in langs:
        if lang in lines:
            out[lang] = lines[lang].model_dump() | {"source": "agent"}
        else:
            t = template_line(kind, context["facts"], lang, (strap or {}).get(lang, draft.headline), turn)
            out[lang] = t.model_dump() | {"source": "template"}
            if agent is not None:
                log.append({"step": "commentary_fallback", "lang": lang})
    return out, log


# ------------------------------------------------------------------ workflow step
class CommentaryExecutor(Executor):
    """Last step of the moment workflow: big moments get a commentary script."""

    def __init__(self, agent, langs: list[str]):
        super().__init__(id="commentary")
        self.agent, self.langs = agent, langs
        self.seen: dict[str, int] = {}

    @handler
    async def comment(self, msg: RenderedMoment, ctx: WorkflowContext[Any, PublishedMoment]) -> None:
        pm = msg.published
        if pm.kind in SPOKEN:
            strap = {r["lang"]: r["lower_third"] for r in reversed(pm.renderings)}
            turn = self.seen[pm.kind] = self.seen.get(pm.kind, -1) + 1
            pm.commentary, log = await write_commentary(self.agent, pm.kind, msg.draft, msg.context, self.langs, strap,
                                                        turn)
            pm.check_log.extend(log)
        await ctx.yield_output(pm)


# ------------------------------------------------------------------ batch CLI
async def batch(prefix: Path, mode: str) -> None:
    from secondscreen.agents.foundry_eval import build_dataset
    from secondscreen.agents.llm import describe_backend, load_dotenv, make_client
    from secondscreen.agents.personas import COMMENTARY_LANGS
    from agent_framework import Agent
    from secondscreen.agents import prompts
    load_dotenv()
    events, moments = prefix.with_suffix(".jsonl"), prefix.with_suffix(".moments.jsonl")
    agent = None
    if mode != "template":
        client = make_client(mode)
        if mode in ("live", "record"):
            print("Backend:", describe_backend())
        agent = Agent(client, prompts.COMMENTARY, name="commentator",
                      description="Writes play-by-play and co-commentator lines for big moments.")
    langs = COMMENTARY_LANGS
    by_id = {m["moment_id"]: m for m in map(json.loads, moments.open(encoding="utf-8"))}
    out = prefix.with_suffix(".commentary.jsonl")
    n = agent_lines = 0
    seen: dict[str, int] = {}
    with out.open("w", encoding="utf-8") as f:
        for row in build_dataset(events, moments):
            if row["kind"] not in SPOKEN:
                continue
            data = json.loads(row["moment_json"])
            m = by_id[row["moment_id"]]
            strap = {r["lang"]: r["lower_third"] for r in reversed(m["renderings"])}
            ctx = {"facts": data["facts"], "roster": data["roster"], "story_so_far": data["story_so_far"]}
            turn = seen[row["kind"]] = seen.get(row["kind"], -1) + 1
            lines, log = await write_commentary(agent, row["kind"], MomentDraft.model_validate(data["draft"]), ctx,
                                                langs, strap, turn)
            f.write(json.dumps({"moment_id": row["moment_id"], "kind": row["kind"], "commentary": lines,
                                "check_log": log}, ensure_ascii=False) + "\n")
            n += 1
            agent_lines += sum(v["source"] == "agent" for v in lines.values())
            print(f"{row['clock']:>6} {row['kind']:18s} {lines['en']['peak']}  {lines['en']['after']}")
    print(f"{n} moments, {agent_lines}/{n * len(langs)} lines from the agent -> {out}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.agents.commentary")
    ap.add_argument("match", help="data/match_<id> (no extension)")
    ap.add_argument("--mode", default="template", choices=["template", "mock", "live", "record", "replay"])
    args = ap.parse_args()
    asyncio.run(batch(Path(args.match.removesuffix(".jsonl")), args.mode))


if __name__ == "__main__":
    main()
