import json

import pytest

pytest.importorskip("agent_framework")

from agent_framework import ChatResponse, Message  # noqa: E402

from secondscreen.agents.factcheck import check_draft, check_rendering  # noqa: E402
from secondscreen.agents.llm import CachingChatClient, MockChatClient  # noqa: E402
from secondscreen.agents.orchestrator import MatchOrchestrator  # noqa: E402
from secondscreen.agents.personas import DEFAULT_PERSONAS  # noqa: E402
from secondscreen.agents.schemas import Claim, MomentDraft, Rendering  # noqa: E402
from secondscreen.simulator import simulate  # noqa: E402

CTX = {
    "facts": {"signal.player": "Ezra Lazaro", "signal.touches_last_12": 18, "signal.ratio": 2.17,
              "signal.pass_completion_before_55": 0.807, "match.clock": "79:46", "match.minute": 79,
              "match.score.HAL": 2, "match.score.RED": 2},
    "roster": ["Ezra Lazaro", "Luca Rask"],
}


def draft(summary="Ezra Lazaro is everywhere.", claims=None):
    return MomentDraft(headline="Lazaro takes over", summary=summary, why_it_matters="Halcyon run through him.",
                       theme="individual", claims=claims or [
                           Claim(text="Ezra Lazaro had 18 touches in the last 12 minutes.",
                                 facts=["signal.player", "signal.touches_last_12"])])


# ------------------------------------------------------- deterministic checks
def test_grounded_draft_passes():
    assert check_draft(draft(), CTX) == []


def test_percentages_and_rounding_allowed():
    d = draft(claims=[Claim(text="They completed 81% of passes before the 55th minute.",
                            facts=["signal.pass_completion_before_55"]),
                      Claim(text="That's 2.2 times the usual rate.", facts=["signal.ratio"])])
    assert check_draft(d, CTX) == []


def test_invented_number_rejected():
    issues = check_draft(draft(summary="Ezra Lazaro has 7 shots."), CTX)
    assert any("7" in i for i in issues)


def test_invented_player_rejected():
    issues = check_draft(draft(summary="Ezra Lazaro and Kofi Garrow combine."), CTX)
    assert any("Kofi Garrow" in i for i in issues)


def test_missing_fact_key_rejected():
    d = draft(claims=[Claim(text="He is fast.", facts=["signal.top_speed"])])
    assert any("don't exist" in i for i in check_draft(d, CTX))


def test_rendering_cannot_add_numbers():
    r = Rendering(persona_id="x", lang="en", lower_third="Lazaro: 18 touches", body="Huge.", stat_chips=[])
    assert check_rendering(r, draft(), CTX) == []
    r2 = Rendering(persona_id="x", lang="en", lower_third="Lazaro: 25 touches", body="Huge.", stat_chips=[])
    assert check_rendering(r2, draft(), CTX)


# --------------------------------------------------------------- pipeline
async def run_match(client, seed=76):
    events, _ = simulate(seed)
    orch = MatchOrchestrator(client)
    for e in events:
        await orch.ingest(e)
    return orch


@pytest.fixture(scope="module")
async def mock_run():
    return await run_match(MockChatClient(inject_error_every=4))


async def test_every_moment_published_for_every_persona(mock_run):
    orch = mock_run
    assert len(orch.store.moments) >= 20
    for m in orch.store.moments:
        assert {r["persona_id"] for r in m["renderings"]} == {p.persona_id for p in DEFAULT_PERSONAS}
        assert m["evidence"], m["kind"]


async def test_hallucinations_caught_and_revised(mock_run):
    orch = mock_run
    revised = [m for m in orch.store.moments if m["attempts"] > 1]
    assert revised, "the injected errors should have triggered revisions"
    for m in revised:
        steps = [(e["step"], e.get("verdict")) for e in m["check_log"] if e["step"] == "fact_check"]
        assert steps[0] == ("fact_check", "rejected")
        assert steps[-1] == ("fact_check", "approved")
        assert "37th" not in m["draft"]["summary"]


async def test_cues_are_machine_readable(mock_run):
    keys = {"cue_id", "match_id", "persona_id", "lang", "type", "clock", "elapsed", "duration_s", "text", "stats"}
    cues = mock_run.store.cues
    assert any(c["type"] == "player_tag" for c in cues), "speed / card tags should appear"
    for c in cues:
        assert keys <= set(c)
        json.dumps(c)


async def test_recap_written_and_grounded(mock_run):
    recap = mock_run.store.recap
    assert recap and recap["source"] == "agent"
    assert recap["recap"]["title"] == "Halcyon City 4-2 Redmarsh Rovers"


class BrokenClient(MockChatClient):
    """Returns garbage for every call: the system must still publish safe moments."""
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        return ChatResponse(messages=[Message(role="assistant", contents=["not json at all"])])


async def test_model_outage_falls_back_safely():
    orch = await run_match(BrokenClient())
    ms = orch.store.moments
    assert ms and all(m["source"] == "fallback" for m in ms)
    goals = [m for m in ms if m["kind"] == "goal"]
    assert len(goals) == 6
    assert orch.store.recap["source"] == "fallback"


class RoguePersona(MockChatClient):
    """Persona agent invents a stat for one persona; only that rendering should be replaced."""
    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        resp = await super()._inner_get_response(messages=messages, stream=stream, options=options, **kwargs)
        data = json.loads(resp.text)
        if "renderings" in data:
            data["renderings"][0]["body"] += " That's 99 sprints today."
            return ChatResponse(messages=[Message(role="assistant", contents=[json.dumps(data)])])
        return resp


async def test_rogue_persona_rendering_replaced():
    orch = await run_match(RoguePersona(), seed=5)
    m = orch.store.moments[0]
    assert all("99 sprints" not in r["body"] for r in m["renderings"])
    assert any(e["step"] == "persona_check" for e in m["check_log"])


async def test_record_then_replay_is_identical(tmp_path):
    cache = tmp_path / "cache.jsonl"
    rec = CachingChatClient(MockChatClient(), cache, mode="record")
    a = await run_match(rec, seed=5)
    rep = CachingChatClient(None, cache, mode="replay")
    b = await run_match(rep, seed=5)
    assert rep.misses == 0 and rep.hits > 0
    assert [m["draft"] for m in a.store.moments] == [m["draft"] for m in b.store.moments]


def test_score_of_one_does_not_license_100_percent():
    ctx = {**CTX, "facts": {**CTX["facts"], "match.score.RED": 1}}
    r = Rendering(persona_id="x", lang="en", lower_third="Lazaro: 18 touches",
                  body="Redmarsh have 1 goal; 99 sprints today.", stat_chips=[])
    assert any("99" in i for i in check_rendering(r, draft(), ctx))


def test_presentation_variants_accepted():
    """Real gpt-4.1-mini phrasings that the first checker wrongly rejected."""
    ctx = {"facts": {**CTX["facts"], "match.momentum": -70.2, "match.clock": "06:59", "match.minute": 6,
                     "signal.players_on_pitch.RED": 10, "signal.avg_outfield_distance_km": 8.46},
           "roster": CTX["roster"], "story_so_far": ["64:44 Redmarsh Rovers are starting to tire"]}
    d = draft(summary="By the 7th minute momentum sat at 70.2.", claims=[
        Claim(text="By the 7th minute the momentum value was 70.2.", facts=["match.momentum"]),
        Claim(text="Redmarsh are down to 10.", facts=["signal.players_on_pitch"]),
        Claim(text="Their outfield players have run 8,460 metres on average.", facts=["signal.avg_outfield_distance_km"]),
        Claim(text="They were already tiring.", facts=["64:44 Redmarsh Rovers are starting to tire"]),
        Claim(text="At 06:59 it was all Redmarsh.", facts=["signal.clock"]),
    ])
    assert check_draft(d, ctx) == []


def test_foreign_words_are_not_players():
    r = Rendering(persona_id="x", lang="es", lower_third="Goles Fontaine", body="Buts Fontaine.", stat_chips=[])
    assert check_rendering(r, draft(), CTX) == []
