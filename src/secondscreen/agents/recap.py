"""Recap agent: half-time / full-time match report built only from approved moments
and final stats, checked with the same grounding rules as live moments."""
from __future__ import annotations

from agent_framework import Agent

from secondscreen.agents import mock_brain, prompts
from secondscreen.agents.factcheck import allowed_numbers, key_numbers, number_ok, numbers_in, unknown_names
from secondscreen.agents.pipeline import _value, payload_block
from secondscreen.agents.schemas import Recap
from secondscreen.stats.engine import StatsEngine

RECAP_TEAM_KEYS = ("goals", "xg", "shots", "shots_on_target", "possession_pct", "pass_completion", "ppda",
                   "high_turnovers", "box_entries", "players_on_pitch")


def recap_facts(engine: StatsEngine) -> dict:
    facts: dict = {}
    for side, tid in (("home", engine.home), ("away", engine.away)):
        ts = engine.teams[tid]
        facts[f"team.{side}.name"] = ts.name
        facts[f"match.score.{side}"] = engine.score[tid]
    for tid, s in engine.team_summary().items():
        for k in RECAP_TEAM_KEYS:
            if s.get(k) is not None:
                facts[f"stats.{engine.teams[tid].name}.{k}"] = s[k]
    players = [p for t in engine.teams.values() for p in t.players.values()]
    ranked = sorted(players, key=lambda p: -(p.goals * 3 + p.assists * 2 + p.xg + p.key_passes * 0.5))[:3]
    for i, p in enumerate(ranked):
        facts.update({f"potm.{i}.name": p.name, f"potm.{i}.team": engine.teams[p.team_id].name,
                      f"potm.{i}.goals": p.goals, f"potm.{i}.assists": p.assists, f"potm.{i}.xg": round(p.xg, 2),
                      f"potm.{i}.shots": p.shots, f"potm.{i}.key_passes": p.key_passes,
                      f"potm.{i}.goal_involvements": p.goals + p.assists,
                      f"potm.{i}.distance_km": round(p.distance_m / 1000, 1)})
    return facts


def moment_brief(m: dict) -> dict:
    return {"moment_id": m["moment_id"], "clock": m["clock"], "kind": m["kind"],
            "headline": m["draft"]["headline"], "summary": m["draft"]["summary"],
            "why_it_matters": m["draft"]["why_it_matters"]}


def check_recap(r: Recap, facts: dict, moments: list[dict], roster: set[str]) -> list[str]:
    by_id = {m["moment_id"]: m for m in moments}
    issues = []
    score_nums = allowed_numbers(v for k, v in facts.items() if k.startswith("match.score"))
    for i, p in enumerate(r.paragraphs):
        bad_ids = [m for m in p.moment_ids if m not in by_id]
        if bad_ids:
            issues.append(f"Paragraph {i} cites unknown moments {bad_ids}.")
        bad_keys = [k for k in p.facts if k not in facts]
        if bad_keys:
            issues.append(f"Paragraph {i} cites unknown fact keys {bad_keys}.")
        allowed = allowed_numbers(facts[k] for k in p.facts if k in facts) | key_numbers(p.facts) | score_nums | {0.0, 1.0}
        for mid in p.moment_ids:
            if mid in by_id:
                m = by_id[mid]
                allowed |= allowed_numbers([m["clock"], m["draft"]["headline"], m["draft"]["summary"],
                                            m["draft"]["why_it_matters"]] + [c["text"] for c in m["draft"]["claims"]])
                allowed |= {float(int(m["minute"]) + 1)}   # 79:46 is "the 80th minute"
        for n in numbers_in(p.text):
            if not number_ok(n, allowed):
                issues.append(f"Paragraph {i} uses {n:g}, which its cited moments and facts don't contain.")
    head_allowed = score_nums | allowed_numbers(facts.values()) | {0.0, 1.0}
    for n in numbers_in(r.title + " " + r.standfirst + " " + r.player_of_the_match_reason):
        if not number_ok(n, head_allowed):
            issues.append(f"Title/standfirst/POTM uses {n:g}, which isn't in the facts.")
    text = " ".join([r.title, r.standfirst, r.player_of_the_match_reason] + [p.text for p in r.paragraphs])
    issues += [f"'{n}' is not in this match." for n in unknown_names(text, roster)]
    if r.player_of_the_match and r.player_of_the_match not in roster:
        issues.append(f"Player of the match '{r.player_of_the_match}' is not in this match.")
    return sorted(set(issues))


async def write_recap(client, engine: StatsEngine, moments: list[dict], max_attempts: int = 2) -> dict:
    agent = Agent(client, prompts.RECAP, name="recap_writer",
                  description="Writes the full-time report from approved moments and final stats.")
    facts = recap_facts(engine)
    briefs = [moment_brief(m) for m in moments]
    roster = {p.name for t in engine.teams.values() for p in t.players.values()}
    log: list[dict] = []
    feedback: list[str] = []
    for attempt in range(1, max_attempts + 1):
        body = {"facts": facts, "moments": briefs}
        if feedback:
            body["feedback"] = feedback
        try:
            resp = await agent.run("Write the match report.\n" + payload_block(body),
                                   options={"response_format": Recap, "temperature": 0.5})
            recap = _value(resp, Recap)
        except Exception as e:  # noqa: BLE001
            log.append({"attempt": attempt, "error": repr(e)[:300]})
            continue
        feedback = check_recap(recap, facts, moments, roster)
        log.append({"attempt": attempt, "issues": feedback})
        if not feedback:
            return {"recap": recap.model_dump(), "source": "agent", "facts": facts, "log": log}
    recap = Recap.model_validate(mock_brain.respond("recap", {"facts": facts, "moments": briefs}, 0, 0))
    return {"recap": recap.model_dump(), "source": "fallback", "facts": facts, "log": log}
