import statistics as st

import pytest

from secondscreen import metrics
from secondscreen.simulator import simulate

SEEDS = range(20)


@pytest.fixture(scope="module")
def matches():
    return [simulate(s) for s in SEEDS]


def test_deterministic():
    a, ta = simulate(123)
    b, tb = simulate(123)
    assert a == b and ta == tb


def test_event_ids_unique_and_ordered(matches):
    for events, _ in matches:
        ids = [e["event_id"] for e in events]
        assert len(ids) == len(set(ids))
        seqs = [e["seq"] for e in events]
        assert seqs == sorted(seqs)
        elapsed = [e["elapsed_seconds"] for e in events]
        assert elapsed == sorted(elapsed), "replay timeline must be monotonic"


def test_coordinates_on_pitch(matches):
    for events, _ in matches:
        for e in events:
            for k, hi in (("x", 105), ("end_x", 105), ("y", 68), ("end_y", 68)):
                if k in e:
                    assert 0 <= e[k] <= hi, (k, e)


def test_score_matches_goal_events(matches):
    for events, truth in matches:
        goals = [e for e in events if e["type"] == "goal"]
        assert len(goals) == sum(truth["final_score"].values())
        assert events[-1]["score"] == truth["final_score"]


def test_no_shared_player_names(matches):
    start = matches[0][0][0]
    names = [p["name"] for side in ("home", "away")
             for grp in ("starting_xi", "bench") for p in start[side][grp]]
    assert len(names) == len(set(names))


def test_realistic_match_totals(matches):
    passes, cmp_rate, shots, goals = [], [], [], []
    for events, truth in matches:
        p = [e for e in events if e["type"] == "pass"]
        passes.append(len(p))
        cmp_rate.append(sum(e["outcome"] == "complete" for e in p) / len(p))
        shots.append(sum(e["type"] == "shot" for e in events))
        goals.append(sum(truth["final_score"].values()))
    assert 800 <= st.mean(passes) <= 1300
    assert 0.76 <= st.mean(cmp_rate) <= 0.88
    assert 18 <= st.mean(shots) <= 34
    assert 1.8 <= st.mean(goals) <= 4.0


def test_pressing_spell_visible_in_raw_events(matches):
    """The hidden pressing arc should raise the presser's pressure + high-turnover
    rate. This is the signal the stats engine has to pick up on its own."""
    lifts = []
    for events, truth in matches:
        arc = next(a for a in truth["arcs"] if a["kind"] == "pressing_spell")
        team, s, e = arc["team_id"], arc["start_min"], arc["end_min"]
        inside = outside = 0
        for ev in events:
            if ev["period"] != 1 or ev.get("team_id") != team:
                continue
            if ev["type"] in ("pressure", "interception", "tackle"):
                m = ev["clock_seconds"] / 60
                if s <= m < e:
                    inside += 1
                elif m < 45:
                    outside += 1
        rate_in = inside / (e - s)
        rate_out = outside / (45 - (e - s))
        lifts.append(rate_in / rate_out)
    assert st.mean(lifts) > 1.3, f"pressing spell lift too weak: {st.mean(lifts):.2f}"


def test_xg_calibration_points():
    assert 0.25 < metrics.expected_goals(94, 34) < 0.33     # penalty spot
    assert 0.5 < metrics.expected_goals(99, 34) < 0.65      # six-yard box
    assert metrics.expected_goals(80, 34) < 0.05            # 25 m
    assert metrics.expected_goals(94, 34, body_part="head") < metrics.expected_goals(94, 34)
    assert metrics.expected_goals(94, 34, situation="penalty") == 0.76
