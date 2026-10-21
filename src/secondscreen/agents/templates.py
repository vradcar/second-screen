"""Deterministic moment templates.

Used three ways: as the safe fallback when the Analyst can't produce a draft
that passes fact-checking, as the offline mock model, and for instant overlay
cues (speed tags etc.) that don't need a language model at all.
"""
from __future__ import annotations

from typing import Any

from secondscreen.agents.schemas import Claim, MomentDraft

# Signals worth a written moment. Everything else becomes an instant cue or is skipped.
NARRATIVE_KINDS = {"goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "pressing_spell",
                   "momentum_swing", "regime_change", "hot_streak", "fatigue_fade", "late_surge"}
INSTANT_KINDS = {"speed_alert", "shot_speed", "distance_milestone", "elite_pass", "yellow_card", "substitution"}

STATE_WORDS = {"opener": "opens the scoring", "equaliser": "equalises", "go_ahead": "puts them ahead",
               "extends_lead": "extends the lead", "pulls_one_back": "pulls one back"}


def pct(v: Any) -> str:
    return f"{round(float(v) * 100)}%" if v is not None else "n/a"


def _score(f: dict) -> tuple[str, list[str]]:
    keys = sorted(k for k in f if k.startswith("match.score."))
    return "-".join(str(f[k]) for k in keys), keys


def is_narrative(signal: dict, story: list[dict] | None = None) -> bool:
    """Worth a written moment? Skips 'end' markers, drifts back to a balanced game, and
    momentum swings that merely echo a goal shown in the last three minutes."""
    if signal["kind"] not in NARRATIVE_KINDS or signal.get("status") == "end":
        return False
    if signal["kind"] == "regime_change" and signal["facts"].get("to") == "balanced":
        return False
    if signal["kind"] == "momentum_swing" and story:
        if any(m["kind"] == "goal" and signal["elapsed"] - m["elapsed"] <= 180 for m in story):
            return False
    return signal["importance"] >= 0.4


def template_draft(signal: dict, context: dict) -> MomentDraft:
    f = context["facts"]
    kind = signal["kind"]
    team = f.get("signal.team", "")
    score, score_keys = _score(f)
    C = Claim

    if kind == "goal":
        scorer = f["signal.scorer"]
        state = f["signal.game_state"]
        claims = [C(text=f"{scorer} scores for {team}.", facts=["signal.scorer", "signal.team"]),
                  C(text=f"The score is now {score}.", facts=score_keys)]
        if f.get("signal.assist"):
            claims.append(C(text=f"{f['signal.assist']} provided the assist.", facts=["signal.assist"]))
        if f.get("signal.shot.xg") is not None:
            claims.append(C(text=f"The chance was worth {f['signal.shot.xg']:.2f} xG.", facts=["signal.shot.xg"]))
        if f.get("signal.comeback_complete"):
            why = f"{team} have come from behind to lead."
            claims.append(C(text=why, facts=["signal.comeback_complete", "signal.game_state"]))
        elif state == "equaliser":
            why = "The game is level again and the pressure flips straight back."
            claims.append(C(text="The goal levels the match.", facts=["signal.game_state"]))
        else:
            why = f"It changes the game state: {STATE_WORDS.get(state, state)}."
            claims.append(C(text=f"The goal {STATE_WORDS.get(state, state)}.", facts=["signal.game_state"]))
        return MomentDraft(headline=f"GOAL: {scorer} {STATE_WORDS.get(state, 'scores')}"[:70],
                           summary=f"{scorer} scores for {team}. It's {score}.", why_it_matters=why,
                           theme="game_state", claims=claims)

    if kind == "red_card":
        p = f["signal.player"]
        return MomentDraft(
            headline=f"Red card: {p} is sent off", theme="discipline",
            summary=f"{p} is shown a second yellow. {team} are down to {f['signal.players_left']}.",
            why_it_matters=f"{team} must play the last {f['match.minutes_remaining']} minutes a player short.",
            claims=[C(text=f"{p} is sent off for a second yellow card.", facts=["signal.player", "signal.reason"]),
                    C(text=f"{team} have {f['signal.players_left']} players left.", facts=["signal.players_left"]),
                    C(text=f"There are {f['match.minutes_remaining']} minutes of normal time left.",
                      facts=["match.minutes_remaining"])])

    if kind == "penalty_awarded":
        return MomentDraft(
            headline=f"Penalty to {team}!", theme="set_piece",
            summary=f"{team} have a penalty. {f['signal.taker']} steps up.",
            why_it_matters=f"It's {score} and this is the best chance a team can get.",
            claims=[C(text=f"{team} are awarded a penalty.", facts=["signal.kind", "signal.team"]),
                    C(text=f"{f['signal.taker']} will take it.", facts=["signal.taker"]),
                    C(text=f"The score is {score}.", facts=score_keys)])

    if kind in ("big_save", "big_chance_missed"):
        p, xg = f["signal.player"], f["signal.xg"]
        xg_key = f"stats.{signal['team_id']}.xg"
        team_xg = f.get(xg_key, xg)
        what = "is denied by the goalkeeper" if kind == "big_save" else "can't take a huge chance"
        return MomentDraft(
            headline=f"{p} {what}"[:70], theme="chance_quality",
            summary=f"{p} shoots from {f['signal.distance_m']} m, a chance worth {xg:.2f} xG.",
            why_it_matters=f"{team} have now created {team_xg} xG in total.",
            claims=[C(text=f"{p} shot from {f['signal.distance_m']} m.", facts=["signal.player", "signal.distance_m"]),
                    C(text=f"The chance was worth {xg:.2f} xG.", facts=["signal.xg"]),
                    C(text=f"The shot was {f['signal.outcome'].replace('_', ' ')}.", facts=["signal.outcome"]),
                    C(text=f"{team} have {team_xg} xG in the match.", facts=[xg_key])])

    if kind == "pressing_spell":
        acts, ratio = f["signal.press_actions_last_6"], f["signal.ratio"]
        opp = f.get("signal.opp_pass_completion_last_6")
        claims = [C(text=f"{team} made {acts} high defensive actions in the last six minutes.",
                    facts=["signal.press_actions_last_6"]),
                  C(text=f"That is {ratio}x their usual pressing rate.", facts=["signal.ratio"])]
        why = "Pressing this high forces mistakes close to goal."
        if opp is not None:
            claims.append(C(text=f"Their opponents completed {pct(opp)} of passes in that spell.",
                            facts=["signal.opp_pass_completion_last_6"]))
            why = f"Their opponents are completing {pct(opp)} of passes under this pressure."
        if f.get("signal.context") == "chasing_the_game":
            why = f"{team} are behind, so they are risking space behind to win the ball back."
            claims.append(C(text=f"{team} are behind.", facts=["signal.context"]))
        return MomentDraft(headline=f"{team} turn up the press", summary=claims[0].text + " " + claims[1].text,
                           why_it_matters=why, theme="pressing", claims=claims)

    if kind == "momentum_swing":
        s5, b5 = f["signal.shots_last_5"], f["signal.box_entries_last_5"]
        return MomentDraft(
            headline=f"Momentum swings to {team}", theme="momentum",
            summary=f"{team} have {s5} shots and {b5} box entries in the last five minutes.",
            why_it_matters="The flow of the game has turned; the other side is now on the back foot.",
            claims=[C(text=f"{team} had {s5} shots in the last five minutes.", facts=["signal.shots_last_5"]),
                    C(text=f"{team} entered the box {b5} times in the last five minutes.",
                      facts=["signal.box_entries_last_5"]),
                    C(text="Momentum moved from one side to the other.",
                      facts=["signal.momentum_before", "signal.momentum_now"])])

    if kind == "regime_change":
        to = f["signal.to"]
        cpm = f["signal.possession_changes_per_min"]
        if to == "chaos":
            return MomentDraft(
                headline="The game has broken open", theme="control_vs_chaos",
                summary=f"The ball is changing hands {cpm} times a minute.",
                why_it_matters="Nobody is in control. Chaos favours direct, quick attacks over patient build-up.",
                claims=[C(text=f"Possession changed {cpm} times a minute over the last five minutes.",
                          facts=["signal.possession_changes_per_min"]),
                        C(text="The match moved into a chaotic phase.", facts=["signal.to"])])
        if to.startswith("control"):
            share = f.get(f"signal.possession_share_last_5.{signal['team_id']}")
            return MomentDraft(
                headline=f"{team} take control", theme="control_vs_chaos",
                summary=f"{team} have had {pct(share)} of the ball in the last five minutes.",
                why_it_matters="Long spells on the ball let them dictate the rhythm and tire the opponent.",
                claims=[C(text=f"{team} had {pct(share)} of possession over the last five minutes.",
                          facts=[f"signal.possession_share_last_5.{signal['team_id']}"]),
                        C(text=f"{team} are controlling the game.", facts=["signal.to", "signal.team"])])
        return MomentDraft(
            headline="The game settles down", theme="control_vs_chaos",
            summary="Neither side is dominating the ball now.",
            why_it_matters="A balanced spell: the next team to take control could decide the game.",
            claims=[C(text="The match moved into a balanced phase.", facts=["signal.to"])])

    if kind == "hot_streak":
        p = f["signal.player"]
        t, e = f["signal.touches_last_12"], f["signal.expected_touches_last_12"]
        return MomentDraft(
            headline=f"{p} is running this game", theme="individual",
            summary=f"{p} has {t} touches in 12 minutes, against {e} expected from his earlier share.",
            why_it_matters=f"{team} are routing their attacks through him.",
            claims=[C(text=f"{p} had {t} touches in the last 12 minutes.", facts=["signal.player", "signal.touches_last_12"]),
                    C(text=f"His earlier share of the ball predicts {e}.", facts=["signal.expected_touches_last_12"]),
                    C(text=f"In that time: {f['signal.shots_last_12']} shot(s), {f['signal.key_passes_last_12']} key pass(es).",
                      facts=["signal.shots_last_12", "signal.key_passes_last_12"])])

    if kind == "fatigue_fade":
        before, now = f["signal.pass_completion_before_55"], f["signal.pass_completion_last_10"]
        return MomentDraft(
            headline=f"{team} are starting to tire", theme="physical",
            summary=f"Their pass completion has dropped from {pct(before)} to {pct(now)} in the last ten minutes.",
            why_it_matters="Tired legs mean slower pressing and looser passing, and space opens up for the opponent.",
            claims=[C(text=f"{team} completed {pct(before)} of passes before the 55th minute.",
                      facts=["signal.pass_completion_before_55"]),
                    C(text=f"They completed {pct(now)} in the last ten minutes.", facts=["signal.pass_completion_last_10"]),
                    C(text=f"Their outfield players have averaged {f['signal.avg_outfield_distance_km']} km.",
                      facts=["signal.avg_outfield_distance_km"])])

    if kind == "late_surge":
        share = f["signal.threat_share_last_8"]
        s, o = f["signal.shots_last_8"], f["signal.opp_shots_last_8"]
        return MomentDraft(
            headline=f"{team} lay siege", theme="momentum",
            summary=f"{team} have produced {pct(share)} of the attacking threat in the last eight minutes.",
            why_it_matters=f"At {score}, they are throwing everything forward.",
            claims=[C(text=f"{team} produced {pct(share)} of the attacking threat in the last eight minutes.",
                      facts=["signal.threat_share_last_8"]),
                    C(text=f"They had {s} shots to {o} in that time.", facts=["signal.shots_last_8", "signal.opp_shots_last_8"]),
                    C(text=f"The score is {score}.", facts=score_keys)])

    raise ValueError(f"no template for {kind}")


# --------------------------------------------------------------- instant cues
LABELS = {
    "en": {"speed": "Top speed", "shot": "Shot speed", "distance": "Distance", "pass": "Pass difficulty",
           "yellow": "Yellow card", "sub_on": "On", "sub_off": "Off"},
    "es": {"speed": "Velocidad punta", "shot": "Velocidad del disparo", "distance": "Distancia",
           "pass": "Dificultad del pase", "yellow": "Tarjeta amarilla", "sub_on": "Entra", "sub_off": "Sale"},
    "fr": {"speed": "Vitesse de pointe", "shot": "Vitesse de frappe", "distance": "Distance",
           "pass": "Difficulté de la passe", "yellow": "Carton jaune", "sub_on": "Entre", "sub_off": "Sort"},
}


def instant_cue(signal: dict, lang: str = "en") -> dict | None:
    """Player tags and stat pop-ups that render without a language model."""
    f, kind = signal["facts"], signal["kind"]
    L = LABELS.get(lang, LABELS["en"])
    if kind == "speed_alert":
        return {"type": "player_tag", "strap": f["player"], "stats": [{"label": L["speed"], "value": f"{f['speed_kmh']} km/h"}]}
    if kind == "shot_speed":
        return {"type": "stat_pop", "strap": f["player"], "stats": [{"label": L["shot"], "value": f"{f['shot_speed_kmh']} km/h"}]}
    if kind == "distance_milestone":
        return {"type": "player_tag", "strap": f["player"], "stats": [{"label": L["distance"], "value": f"{f['distance_km']} km"}]}
    if kind == "elite_pass":
        return {"type": "stat_pop", "strap": f"{f['player']} → {f['recipient']}",
                "stats": [{"label": L["pass"], "value": f"{f['difficulty']}/10"}]}
    if kind == "yellow_card":
        return {"type": "player_tag", "strap": f["player"], "stats": [{"label": L["yellow"], "value": "🟨"}]}
    if kind == "substitution":
        return {"type": "lower_third", "strap": f"{L['sub_on']}: {f['on']} · {L['sub_off']}: {f['off']}", "stats": []}
    return None
