"""The moment workflow, built on Microsoft Agent Framework.

    AnalystRequest ──► Analyst ──draft──► Fact-Checker ──approved──► Persona ──► PublishedMoment
                         ▲                    │   │
                         └──── revise ────────┘   └── rejected twice ──► Fallback ──► Persona
                         (feedback, max 2 retries)                     (safe template)

- The Analyst writes a moment card with claims citing FACT keys.
- The Fact-Checker runs deterministic grounding checks, then an LLM judge, and either
  approves, sends the draft back with specific feedback, or gives up.
- The Fallback produces a template card from the facts so air time is never lost.
- The Persona agent renders the approved card for each viewer profile; any rendering that
  adds a number or person is replaced with a safe one.
Agent failures (timeouts, bad JSON) take the same recovery path as rejected drafts.
"""
from __future__ import annotations

import json
import time
from typing import Any

from agent_framework import Agent, Executor, WorkflowBuilder, WorkflowContext, handler

from secondscreen.agents import prompts
from secondscreen.agents.factcheck import check_draft, check_rendering
from secondscreen.agents.personas import DEFAULT_PERSONAS, Persona
from secondscreen.agents.schemas import (RenderedMoment, AnalystRequest, ApprovedMoment, CheckedDraft, FailedDraft, JudgeVerdict,
                                         MomentDraft, PersonaBatch, PersonaVerdicts, PublishedMoment, Rendering)
from secondscreen.agents.templates import template_draft
from secondscreen.agents.commentary import CommentaryExecutor, langs_for

MAX_ATTEMPTS = 3   # first draft + 2 revisions


def payload_block(obj: Any) -> str:
    return "```json\n" + json.dumps(obj, ensure_ascii=False, default=str) + "\n```"


def signal_stub(signal: dict) -> dict:
    return {k: signal[k] for k in ("signal_id", "kind", "status", "team_id", "player_id", "clock", "minute", "period",
                                   "importance") if k in signal}


def _value(resp, model):
    """Structured output if the client parsed it, else parse the text ourselves."""
    try:
        v = resp.value
    except Exception:  # noqa: BLE001 - some clients raise on parse failure
        v = None
    return v if isinstance(v, model) else model.model_validate_json(resp.text)


class AnalystExecutor(Executor):
    def __init__(self, agent: Agent):
        super().__init__(id="analyst")
        self.agent = agent

    @handler
    async def write(self, req: AnalystRequest, ctx: WorkflowContext[CheckedDraft | FailedDraft]) -> None:
        body = {"signal": signal_stub(req.signal), "facts": req.context["facts"],
                "story_so_far": req.context["story_so_far"], "feedback": req.feedback}
        if req.previous:
            body["previous_draft"] = req.previous.model_dump()
        prompt = (f"Moment flagged by the stats engine (attempt {req.attempt}).\n" + payload_block(body))
        t0 = time.perf_counter()
        try:
            resp = await self.agent.run(prompt, options={"response_format": MomentDraft, "temperature": 0.4})
            draft = _value(resp, MomentDraft)
        except Exception as e:  # noqa: BLE001
            req.log.append({"step": "analyst", "attempt": req.attempt, "error": repr(e)[:300]})
            await ctx.send_message(FailedDraft(req, [f"analyst failed: {e!r}"[:300]], req.log))
            return
        req.log.append({"step": "analyst", "attempt": req.attempt, "ms": round((time.perf_counter() - t0) * 1000),
                        "headline": draft.headline})
        await ctx.send_message(CheckedDraft(req, draft))


class FactCheckExecutor(Executor):
    def __init__(self, judge: Agent | None, max_attempts: int = MAX_ATTEMPTS):
        super().__init__(id="fact_checker")
        self.judge = judge
        self.max_attempts = max_attempts

    async def llm_judge(self, msg: CheckedDraft) -> list[str]:
        prompt = "Check this draft.\n" + payload_block({"facts": msg.request.context["facts"],
                                                       "draft": msg.draft.model_dump()})
        resp = await self.judge.run(prompt, options={"response_format": JudgeVerdict, "temperature": 0.0})
        v = _value(resp, JudgeVerdict)
        issues = [f"Claim {cv.index} unsupported: {cv.reason}" for cv in v.verdicts if not cv.supported]
        if not v.narrative_supported:
            issues.append(f"Narrative not supported by claims: {v.feedback}")
        return issues

    @handler
    async def check(self, msg: CheckedDraft,
                    ctx: WorkflowContext[AnalystRequest | ApprovedMoment | FailedDraft]) -> None:
        req = msg.request
        issues = check_draft(msg.draft, req.context)
        stage = "rules"
        if not issues and self.judge is not None:
            stage = "judge"
            try:
                issues = await self.llm_judge(msg)
            except Exception as e:  # noqa: BLE001 - judge outage: rules already passed, approve with a note
                req.log.append({"step": "judge", "attempt": req.attempt, "error": repr(e)[:300]})
                issues = []
        req.log.append({"step": "fact_check", "attempt": req.attempt, "stage": stage,
                        "verdict": "approved" if not issues else "rejected", "issues": issues})
        if not issues:
            await ctx.send_message(ApprovedMoment(req, msg.draft, "agent", req.log))
        elif req.attempt < self.max_attempts:
            await ctx.send_message(AnalystRequest(req.signal, req.context, req.attempt + 1, issues, msg.draft, req.log))
        else:
            await ctx.send_message(FailedDraft(req, issues, req.log))


class FallbackExecutor(Executor):
    def __init__(self):
        super().__init__(id="fallback")

    @handler
    async def recover(self, msg: FailedDraft, ctx: WorkflowContext[ApprovedMoment]) -> None:
        draft = template_draft(msg.request.signal, msg.request.context)
        issues = check_draft(draft, msg.request.context)
        msg.check_log.append({"step": "fallback", "reasons": msg.reasons, "template_issues": issues})
        await ctx.send_message(ApprovedMoment(msg.request, draft, "fallback", msg.check_log))


def clip(text: str, n: int) -> str:
    """Shorten at a word boundary."""
    if len(text) <= n:
        return text
    cut = text[: n - 1].rsplit(" ", 1)[0].rstrip(",;:-")
    return cut + "…"


def safe_rendering(p: Persona, draft: MomentDraft) -> Rendering:
    return Rendering(persona_id=p.persona_id, lang="en", lower_third=clip(draft.headline, 60),
                     body=clip(draft.summary if p.mode == "casual" else f"{draft.summary} {draft.why_it_matters}", 240),
                     stat_chips=[])


class PersonaExecutor(Executor):
    def __init__(self, agent: Agent, personas: list[Persona], match_id_ref: dict, judge: Agent | None = None):
        super().__init__(id="persona")
        self.agent = agent
        self.judge = judge
        self.personas = personas
        self.match = match_id_ref   # {"match_id": ..., "count": n}

    @handler
    async def render(self, msg: ApprovedMoment, ctx: WorkflowContext[RenderedMoment]) -> None:
        req, draft = msg.request, msg.draft
        renderings: dict[str, Rendering] = {}
        log = msg.check_log
        try:
            prompt = "Render this approved moment for each persona.\n" + payload_block({
                "moment": draft.model_dump(), "facts": req.context["facts"],
                "personas": [p.to_prompt() for p in self.personas]})
            resp = await self.agent.run(prompt, options={"response_format": PersonaBatch, "temperature": 0.6})
            for r in _value(resp, PersonaBatch).renderings:
                problems = check_rendering(r, draft, req.context)
                if problems:
                    log.append({"step": "persona_check", "persona": r.persona_id, "rejected": problems})
                else:
                    renderings[r.persona_id] = r
        except Exception as e:  # noqa: BLE001
            log.append({"step": "persona", "error": repr(e)[:300]})
        if renderings and self.judge is not None:
            await _judge_renderings(self.judge, renderings, draft, req.context, log)
        for p in self.personas:
            if p.persona_id not in renderings:
                renderings[p.persona_id] = safe_rendering(p, draft)
                log.append({"step": "persona_fallback", "persona": p.persona_id})
        self.match["count"] += 1
        sig = req.signal
        moment_id = f"{self.match['match_id']}-M{self.match['count']:03d}"
        duration = 10 if sig["importance"] >= 0.8 else 7
        cues = [{
            "cue_id": f"{moment_id}-{pid}", "moment_id": moment_id, "match_id": self.match["match_id"],
            "persona_id": pid, "lang": r.lang, "type": "lower_third", "clock": sig["clock"],
            "elapsed": sig["elapsed"], "duration_s": duration, "priority": sig["importance"],
            "team_id": sig.get("team_id"), "player_id": sig.get("player_id"),
            "text": {"strap": r.lower_third, "card": r.body},
            "stats": [c.model_dump() for c in r.stat_chips], "evidence": sig.get("evidence", []),
        } for pid, r in renderings.items()]
        from secondscreen.agents.factcheck import resolve_keys
        cited, _ = resolve_keys({k for c in draft.claims for k in c.facts}, req.context["facts"],
                                req.context.get("story_so_far"))
        cited_facts = {k: req.context["facts"][k] for k in cited if k in req.context["facts"]}
        await ctx.send_message(RenderedMoment(draft=draft, context=req.context, published=PublishedMoment(
            moment_id=moment_id, signal_id=sig["signal_id"], kind=sig["kind"], clock=sig["clock"],
            minute=sig["minute"], elapsed=sig["elapsed"], team_id=sig.get("team_id"), player_id=sig.get("player_id"),
            importance=sig["importance"], source=msg.source, attempts=req.attempt, draft=draft.model_dump(),
            renderings=[r.model_dump() for r in renderings.values()], cues=cues,
            evidence=sig.get("evidence", []), check_log=log, facts=cited_facts)))


async def _judge_renderings(judge: Agent, renderings: dict, draft: MomentDraft, context: dict, log: list) -> None:
    prompt = "Check these renderings.\n" + payload_block({
        "approved_moment": draft.model_dump(), "facts": context["facts"],
        "renderings": [r.model_dump() for r in renderings.values()]})
    try:
        resp = await judge.run(prompt, options={"response_format": PersonaVerdicts, "temperature": 0.0})
        verdicts = _value(resp, PersonaVerdicts).verdicts
    except Exception as e:  # noqa: BLE001 - judge outage: rules already passed, keep renderings
        log.append({"step": "persona_judge", "error": repr(e)[:300]})
        return
    for v in verdicts:
        if not v.supported and v.persona_id in renderings:
            del renderings[v.persona_id]
            log.append({"step": "persona_check", "persona": v.persona_id, "rejected": [f"judge: {v.reason}"]})


def build_moment_workflow(client, personas: list[Persona] | None = None, match_ref: dict | None = None,
                          use_judge: bool = True):
    """Assemble the agents and wire them into a workflow graph."""
    analyst = Agent(client, prompts.ANALYST, name="tactical_analyst",
                    description="Explains why a flagged match moment matters, with cited facts.")
    judge = Agent(client, prompts.JUDGE, name="fact_checker",
                  description="Verifies every claim against the stats engine's facts.") if use_judge else None
    persona = Agent(client, prompts.PERSONA, name="persona_renderer",
                    description="Adapts approved moments for each viewer profile and language.")

    a = AnalystExecutor(analyst)
    fc = FactCheckExecutor(judge)
    fb = FallbackExecutor()
    persona_judge = Agent(client, prompts.PERSONA_JUDGE, name="persona_fact_checker",
                          description="Checks each viewer's version of a moment against the approved facts.") if use_judge else None
    pe = PersonaExecutor(persona, personas or DEFAULT_PERSONAS,
                         match_ref if match_ref is not None else {"match_id": "M", "count": 0}, judge=persona_judge)

    commentator = Agent(client, prompts.COMMENTARY, name="commentator",
                        description="Writes play-by-play and co-commentator lines for big moments.")
    co = CommentaryExecutor(commentator, langs_for(personas or DEFAULT_PERSONAS))

    return (WorkflowBuilder(name="second_screen_moment", start_executor=a, max_iterations=20)
            .add_edge(a, fc, condition=lambda m: isinstance(m, CheckedDraft))
            .add_edge(a, fb, condition=lambda m: isinstance(m, FailedDraft))
            .add_edge(fc, a, condition=lambda m: isinstance(m, AnalystRequest))
            .add_edge(fc, pe, condition=lambda m: isinstance(m, ApprovedMoment))
            .add_edge(fc, fb, condition=lambda m: isinstance(m, FailedDraft))
            .add_edge(fb, pe)
            .add_edge(pe, co)
            .build())
