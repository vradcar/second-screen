import json
from pathlib import Path

from secondscreen.agents.spotter import Spotter, call_lead

DATA = Path(__file__).resolve().parents[1] / "data"


def test_calls_match_agent_moments_and_land_on_the_event():
    events = [json.loads(x) for x in (DATA / "match_SS00076.jsonl").open(encoding="utf-8")]
    by_id = {e["event_id"]: e for e in events}
    moments = {m["signal_id"]: m for m in map(json.loads, (DATA / "match_SS00076.moments.jsonl").open(encoding="utf-8"))}
    sp = Spotter(["en", "es"])
    calls = [c for e in events for c in sp.feed(e)]
    goals = [c for c in calls if c["kind"] == "goal"]
    assert len(goals) == sum(e["type"] == "goal" for e in events)
    for c in calls:
        assert c["signal_id"] in moments and moments[c["signal_id"]]["kind"] == c["kind"]   # pundit follows the call
        assert c["commentary"]["en"]["peak"] and c["commentary"]["en"]["pundit"] == ""
    first_goal = next(e for e in events if e["type"] == "goal")
    assert goals[0]["at"] == first_goal["elapsed_seconds"]


def test_call_lead_scales_with_speed():
    assert call_lead(1, 6) == 6 and call_lead(10, 6) == 40


def test_on_air_can_kick_off_a_brand_new_match(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    monkeypatch.setenv("SECONDSCREEN_RUNTIME", str(tmp_path))
    monkeypatch.setenv("SECONDSCREEN_MAX_SPEED", "600")
    from secondscreen.server.app import app
    with TestClient(app) as client:
        r = client.post("/api/broadcast/start?seed=777&speed=600")
        assert r.status_code == 200 and r.json()["match"] == "SS00777"
        assert r.json()["agents"] in ("mock", "live")             # no recorded run for a new match
        assert (tmp_path / "match_SS00777.jsonl").exists()
        client.post("/api/broadcast/stop")
