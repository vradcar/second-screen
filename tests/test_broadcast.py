import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("agent_framework")

from fastapi.testclient import TestClient  # noqa: E402

from secondscreen.server.app import app  # noqa: E402


def collect(ws, until=("end",), limit=20000):
    seen = {}
    for _ in range(limit):
        m = json.loads(ws.receive_text())
        seen[m["t"]] = seen.get(m["t"], 0) + 1
        if m["t"] in until:
            break
    return seen


def test_broadcast_idle_then_on_air_then_end(monkeypatch):
    monkeypatch.setenv("SECONDSCREEN_MAX_SPEED", "600")
    with TestClient(app) as c:
        assert c.get("/api/broadcast").json()["state"] == "idle"
        with c.websocket_connect("/ws/broadcast") as ws:
            assert json.loads(ws.receive_text())["t"] == "idle"
            r = c.post("/api/broadcast/start", params={"speed": 600, "agents": "recorded"}).json()
            assert r["state"] == "on_air" and r["feed"] == "memory" and r["store"] == "memory"
            seen = collect(ws)
        for kind in ("meta", "ev", "snap", "clock", "moment", "cue", "recap", "end"):
            assert seen.get(kind), kind
        assert c.get("/api/broadcast").json()["state"] == "ended"
        # A late viewer gets the full backlog from the store.
        with c.websocket_connect("/ws/broadcast") as ws:
            late = collect(ws)
        assert late.get("meta") and late.get("moment", 0) >= 20 and late.get("recap")
