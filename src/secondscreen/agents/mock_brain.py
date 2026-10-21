"""What the offline mock model 'says' for each agent role. Deterministic."""
from __future__ import annotations

from secondscreen.agents.schemas import MomentDraft
from secondscreen.agents.templates import template_draft


def clip(text: str, n: int) -> str:
    if len(text) <= n:
        return text
    return text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"


def respond(role: str, payload: dict, call_no: int, inject_error_every: int) -> dict:
    if role == "analyst":
        sig = payload["signal"]
        draft = template_draft(sig, {"facts": payload["facts"]})
        if inject_error_every and not payload.get("feedback") and call_no % inject_error_every == 0:
            # A plausible-sounding hallucination the deterministic checker must catch.
            draft.summary += " It is their 37th attack of the half."
        return draft.model_dump()

    if role == "judge":
        n = len(payload["draft"]["claims"])
        return {"verdicts": [{"index": i, "supported": True, "reason": "matches cited facts"} for i in range(n)],
                "narrative_supported": True, "feedback": ""}

    if role == "persona_judge":
        return {"verdicts": [{"persona_id": r["persona_id"], "supported": True, "reason": "consistent"}
                             for r in payload["renderings"]]}

    if role == "persona":
        m = MomentDraft.model_validate(payload["moment"])
        facts = payload["facts"]
        chips = []
        for c in m.claims:
            for k in c.facts:
                v = facts.get(k)
                if isinstance(v, (int, float)) and not isinstance(v, bool) and len(chips) < 2:
                    chips.append({"label": k.split(".")[-1].replace("_", " "), "value": str(v)})
        out = []
        for p in payload["personas"]:
            body = m.summary if p["mode"] == "casual" else f"{m.summary} {m.why_it_matters}"
            out.append({"persona_id": p["persona_id"], "lang": p.get("lang", "en"),
                        "lower_third": clip(m.headline, 60), "body": clip(body, 240),
                        "stat_chips": chips if p["mode"] == "analyst" else chips[:1]})
        return {"renderings": out}

    if role == "recap":
        facts, moments = payload["facts"], payload["moments"]
        title = f"{facts['team.home.name']} {facts['match.score.home']}-{facts['match.score.away']} {facts['team.away.name']}"
        goals = [m for m in moments if m["kind"] == "goal"]
        turning = [m for m in moments if m["kind"] in ("red_card", "late_surge", "fatigue_fade", "momentum_swing")]
        paras = []
        if goals:
            paras.append({"text": " ".join(f"{m['clock']}: {m['headline']}." for m in goals[:3]),
                          "moment_ids": [m["moment_id"] for m in goals[:3]], "facts": []})
        if turning:
            paras.append({"text": " ".join(m["summary"] for m in turning[:3]),
                          "moment_ids": [m["moment_id"] for m in turning[:3]], "facts": []})
        if len(goals) > 3:
            paras.append({"text": " ".join(f"{m['clock']}: {m['headline']}." for m in goals[3:]),
                          "moment_ids": [m["moment_id"] for m in goals[3:]], "facts": []})
        potm = facts.get("potm.0.name", "")
        return {"title": title, "standfirst": goals[-1]["summary"] if goals else "A goalless match.",
                "paragraphs": paras or [{"text": "No major moments.", "moment_ids": [], "facts": []}],
                "player_of_the_match": potm,
                "player_of_the_match_reason": f"{potm} was involved in {facts.get('potm.0.goal_involvements', 0)} goals.",
                "player_of_the_match_facts": ["potm.0.name", "potm.0.goal_involvements"]}

    raise ValueError(f"mock has no role {role}")
