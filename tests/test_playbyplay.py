import json
from pathlib import Path

from secondscreen.agents.factcheck import unknown_names
from secondscreen.agents.spotter import Spotter

DATA = Path(__file__).resolve().parents[1] / "data"


def _run(langs=("en", "es", "fr")):
    sp, lines, calls, events = Spotter(list(langs)), [], [], []
    for row in (DATA / "match_SS00076.jsonl").open(encoding="utf-8"):
        e = json.loads(row)
        events.append(e)
        calls += sp.feed(e)
        lines += sp.take_lines()
    return lines, calls, events


def test_commentary_runs_through_the_whole_match():
    lines, calls, events = _run()
    assert len(lines) > 400
    gaps = [b["at"] - a["at"] for a, b in zip(lines, lines[1:])]
    assert sorted(gaps)[int(len(gaps) * 0.9)] < 30                 # rarely a long silence
    texts = [ln["text"]["en"] for ln in lines]
    assert texts[0] == "And we're under way!" and texts[-1].startswith("And there's the final whistle!")
    assert any("half-time" in t for t in texts)
    assert all(set(ln["text"]) == {"en", "es", "fr"} and all(ln["text"].values()) for ln in lines)


def test_running_lines_leave_big_moments_to_the_call():
    lines, calls, events = _run(("en",))
    goal_times = [e["elapsed_seconds"] for e in events if e["type"] == "goal"]
    for g in goal_times:
        assert not [ln for ln in lines if g < ln["at"] < g + 8]     # quiet while the call and celebration play


def test_running_lines_only_name_real_players():
    lines, _, events = _run(("en",))
    roster = {p["name"] for side in ("home", "away") for k in ("starting_xi", "bench") for p in events[0][side][k]}
    surnames = {n.split()[-1] for n in roster}
    for ln in lines:
        assert not unknown_names(ln["text"]["en"], roster)
    said = {w.strip(".,!'s") for ln in lines for w in ln["text"]["en"].split() if w[:1].isupper()}
    assert said & surnames
