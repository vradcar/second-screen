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
    intro = [ln for ln in lines if ln["kind"] == "intro"]
    assert intro[0]["text"]["en"].startswith("Good afternoon, and welcome to Halcyon Park")
    assert "And we're under way!" in texts and texts[-1].startswith("And there's the final whistle!")
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


def test_pre_match_uses_the_season_and_the_table():
    lines, _, _ = _run(("en",))
    intro = " ".join(ln["text"]["en"] for ln in lines if ln["kind"] == "intro")
    assert "Second against third" in intro                      # from the season standings
    assert "goals already this season" in intro and "Here we go!" in intro


def test_spoken_lines_use_football_language_not_analytics():
    import re
    from secondscreen.agents.commentary import JARGON
    lines, calls, _ = _run(("en",))
    for ln in lines:
        assert not JARGON.search(ln["text"]["en"]), ln["text"]["en"]
    for c in calls:
        line = c["commentary"]["en"]
        assert not JARGON.search(" ".join((line["build"], line["peak"], line["after"], line["pundit"])))
    players = [ln for ln in lines if ln["kind"] == "colour" and ln["key"].startswith("p_")]
    assert len(players) >= 8                                    # stories about players, not just teams
    assert not any(re.search(r"\bxG\b", ln["text"]["en"]) for ln in lines)


def test_commentary_reacts_to_context_like_a_broadcast():
    lines, _, _ = _run(("en", "es", "fr"))
    keys = {ln["key"] for ln in lines}
    # where the ball goes, the state of the move, and what's happened before
    assert {"move", "back_gk", "danger_fk", "sub_touch", "keeper_busy"} <= keys
    assert keys & {"booked_foul", "booked_tackle"} and keys & {"fresh_legs", "sub"}
    assert {"t15", "t30", "t60", "t75"} <= keys
    # the game's story is an exchange: commentator sets it up, the pundit answers
    stories = [ln for ln in lines if ln["kind"] == "story"] + [ln["follow"] for ln in lines
                                                                if ln.get("follow", {}).get("kind") == "story"]
    stories = [s for s in stories if s["role"] == "commentator"]
    assert stories and all(s["follow"]["role"] == "pundit" for s in stories)
    # bookings and the clock are never dropped by the viewer's box
    assert all(ln.get("priority") for ln in lines if ln["key"] in ("yellow", "t75", "corner"))
    # it follows play mostly by name, not "X to Y" every line
    flow = [ln for ln in lines if ln["key"] in ("pass", "name")]
    assert sum(ln["key"] == "name" for ln in flow) > sum(ln["key"] == "pass" for ln in flow)


def test_booked_player_is_remembered():
    lines, _, events = _run(("en",))
    first_yellow = next(e for e in events if e["type"] == "card" and e["card"] == "yellow")
    later = [ln for ln in lines if ln["key"] in ("booked_foul", "booked_tackle")]
    assert later and all(ln["at"] > first_yellow["elapsed_seconds"] for ln in later)
