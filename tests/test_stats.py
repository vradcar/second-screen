import pytest

from secondscreen.simulator import simulate
from secondscreen.stats import StatsEngine


def run(seed):
    events, truth = simulate(seed)
    eng = StatsEngine()
    for ev in events:
        eng.ingest(ev)
    return eng, events, truth


@pytest.fixture(scope="module")
def demo():
    return run(76)


def test_totals_match_raw_events(demo):
    eng, events, truth = demo
    snap = eng.snapshot()
    assert snap["score"] == truth["final_score"]
    for team, stats in snap["teams"].items():
        raw_shots = sum(1 for e in events if e["type"] == "shot" and e["team_id"] == team)
        raw_passes = sum(1 for e in events if e["type"] == "pass" and e["team_id"] == team)
        assert stats["shots"] == raw_shots
        assert stats["passes"] == raw_passes
        assert stats["goals"] == truth["final_score"][team]


def test_possession_sums_to_100(demo):
    eng, _, _ = demo
    assert abs(sum(eng.possession_pct().values()) - 100) < 0.2


def test_every_signal_has_valid_evidence(demo):
    """The Fact-Checker relies on this: evidence IDs must point at real events."""
    eng, events, _ = demo
    ids = {e["event_id"] for e in events}
    for sig in eng.signals:
        assert set(sig.evidence) <= ids, sig.kind
        if sig.kind in ("goal", "red_card", "big_save", "big_chance_missed", "pressing_spell",
                        "hot_streak", "speed_alert") and sig.status != "end":
            assert sig.evidence, f"{sig.kind} has no evidence"


def test_goal_signals_carry_game_state(demo):
    eng, _, _ = demo
    goals = [s for s in eng.signals if s.kind == "goal"]
    assert len(goals) == 6
    states = [g.facts["game_state"] for g in goals]
    assert states[0] == "opener"
    assert "equaliser" in states
    assert any(g.facts["comeback_complete"] for g in goals)


def test_demo_story_detected(demo):
    """Seed 76: Redmarsh go down to ten, fade, and Halcyon surge late."""
    eng, _, _ = demo
    kinds = {(s.kind, s.team_id) for s in eng.signals}
    assert ("red_card", "RED") in kinds
    assert ("late_surge", "HAL") in kinds
    assert ("fatigue_fade", "RED") in kinds


def test_signal_volume_is_watchable(demo):
    """A broadcast can't flash a graphic every minute."""
    eng, _, _ = demo
    major = [s for s in eng.signals if s.importance >= 0.5]
    assert 10 <= len(major) <= 45


def test_streaming_matches_batch():
    """Ingesting event-by-event must give the same result however it's chunked."""
    events, _ = simulate(5)
    a, b = StatsEngine(), StatsEngine()
    out_a = [s.to_dict() for e in events for s in a.ingest(e)]
    for e in events:
        b.ingest(e)
    assert out_a == [s.to_dict() for s in b.signals]
