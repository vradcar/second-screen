from secondscreen.dataset import LEAGUE, build, clubs, fixtures


def test_fixtures_are_a_double_round_robin():
    fx = fixtures()
    n = len(LEAGUE)
    assert len(fx) == n * (n - 1)
    assert len({(h, a) for _, h, a in fx}) == len(fx)               # every pairing once each way
    for md in range(1, 2 * (n - 1) + 1):
        teams = [t for d, h, a in fx if d == md for t in (h, a)]
        assert sorted(teams) == sorted(r[0] for r in LEAGUE)         # everyone plays once per matchday


def test_demo_clubs_unchanged_and_names_unique():
    from secondscreen.simulator.teams import default_clubs
    league, (hal, red) = clubs(), default_clubs()
    assert [p.name for p in league["HAL"].players] == [p.name for p in hal.players]
    assert [p.name for p in league["RED"].players] == [p.name for p in red.players]
    names = [p.name for c in league.values() for p in c.players]
    assert len(names) == len(set(names))


def test_tables_link_up():
    t = build(limit=2)
    mids = {m["match_id"] for m in t["matches"]}
    assert {e["match_id"] for e in t["events"]} == mids
    ev_ids = {e["event_id"] for e in t["events"]}
    import json
    assert all(set(json.loads(s["evidence"])) <= ev_ids for s in t["signals"])   # evidence points at real events
    assert sum(r["played"] for r in t["standings"]) == 4
