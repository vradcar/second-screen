import json
from pathlib import Path

from secondscreen.agents.commentary import SPOKEN, check_line, template_line
from secondscreen.agents.foundry_eval import build_dataset

DATA = Path(__file__).resolve().parents[1] / "data"


def _rows():
    for r in build_dataset(DATA / "match_SS00076.jsonl", DATA / "match_SS00076.moments.jsonl"):
        if r["kind"] in SPOKEN:
            d = json.loads(r["moment_json"])
            yield r, {"facts": d["facts"], "roster": d["roster"], "story_so_far": d["story_so_far"]}


def test_every_template_line_is_grounded_in_three_languages():
    n = 0
    for r, ctx in _rows():
        for lang in ("en", "es", "fr"):
            for turn in range(3):
                line = template_line(r["kind"], ctx["facts"], lang, "fallback", turn)
                assert line.after, (r["kind"], lang)
                assert check_line(line, ctx, lang) == [], (r["clock"], r["kind"], lang, line)
                n += 1
    assert n > 100


def test_goal_calls_follow_the_score():
    calls = {r["clock"]: template_line("goal", ctx["facts"], "en") for r, ctx in _rows() if r["kind"] == "goal"}
    assert calls["11:55"].after.startswith("Bastian Fontaine! Halcyon City lead 1-0")
    assert "Level at 2-2" in calls["79:46"].after and "headed" in calls["79:46"].peak
    assert template_line("goal", next(c for r, c in _rows() if r["clock"] == "14:25")["facts"], "es").peak == "¡Gooool de cabeza!"


def test_checker_rejects_invented_numbers_and_players():
    r, ctx = next(_rows())
    bad = template_line(r["kind"], ctx["facts"], "en")
    first = ctx["roster"][0].split()[0]
    bad.pundit = f"That's 987 shots this season, and {first} Smithers knows it."
    problems = check_line(bad, ctx, "en")
    assert any("number 987" in p for p in problems)
    assert any("unknown player" in p for p in problems)


async def test_workflow_attaches_commentary_to_goals():
    from secondscreen.agents.llm import MockChatClient
    from secondscreen.agents.orchestrator import MatchOrchestrator
    o = MatchOrchestrator(MockChatClient())
    for line in (DATA / "match_SS00076.jsonl").open(encoding="utf-8"):
        e = json.loads(line)
        if e["elapsed_seconds"] > 760:
            break
        await o.ingest(e)
    goal = next(m for m in o.store.moments if m["kind"] == "goal")
    assert set(goal["commentary"]) == {"en", "es", "fr"}
    assert goal["commentary"]["en"]["peak"] and goal["commentary"]["fr"]["pundit"]
