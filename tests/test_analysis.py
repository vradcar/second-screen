import json
from pathlib import Path

from secondscreen.analysis import analyse

DATA = Path(__file__).resolve().parents[1] / "data"
EVENTS = [json.loads(x) for x in (DATA / "match_SS00076.jsonl").open(encoding="utf-8")]


def test_full_match_numbers_hold_together():
    a = analyse(EVENTS)
    assert a["ready"] and len(a["players"]) == 36
    goals = sum(p["goals"] for p in a["players"])
    assert goals == sum(1 for e in EVENTS if e["type"] == "goal") == len([k for k in a["key_events"] if k["kind"] == "goal"])
    assert len(a["shots"]) == sum(1 for e in EVENTS if e["type"] == "shot")
    assert all(0 <= s["x"] <= 105 and 0 <= s["y"] <= 68 for s in a["shots"])
    assert all(s["x"] > 52.5 for s in a["shots"] if s["outcome"] == "goal")     # everyone attacks left to right
    for tm in (a["home"], a["away"]):
        assert abs(a["xg_flow"][tm][-1][1] - sum(s["xg"] for s in a["shots"] if s["team_id"] == tm)) < 0.05
        assert a["pass_networks"][tm]["nodes"] and a["pass_networks"][tm]["edges"]


def test_minutes_follow_subs_and_red_cards():
    a = analyse(EVENTS)
    by = {p["player_id"]: p for p in a["players"]}
    sub = next(k for k in a["key_events"] if k["kind"] == "sub")
    assert 0 < by[sub["player_id"]]["minutes"] < 45 and by[sub["off_id"]]["minutes"] > 45
    red = next(k for k in a["key_events"] if k["kind"] == "red")
    assert by[red["player_id"]]["minutes"] < 60 and by[red["player_id"]]["red_card"]
    assert all(p["minutes"] == 0 for p in a["players"] if not p["starter"] and p["player_id"] not in
               {k["player_id"] for k in a["key_events"] if k["kind"] == "sub"})


def test_only_what_has_happened_so_far():
    early = analyse(EVENTS, upto=700)
    assert early["clock"] < "11:55" and not [k for k in early["key_events"] if k["kind"] == "goal"]


def test_desk_series_line_up_with_the_match_clock():
    a = analyse(EVENTS)
    assert [r["label"] for r in a["ppda"]] == ["0-15'", "15-30'", "30-45'", "45-60'", "60-75'", "75-90'"]
    assert all(s["elapsed"] >= 0 for s in a["shots"]) and a["second_half"]
    assert len(a["zones"]) == 18
    assert all(z["share"] is None or 0 <= z["share"] <= 1 for z in a["zones"])
