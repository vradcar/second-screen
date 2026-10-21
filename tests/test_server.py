import json

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("agent_framework")

from fastapi.testclient import TestClient  # noqa: E402

from secondscreen.server.app import app  # noqa: E402


def test_stream_delivers_pipeline_output():
    c = TestClient(app)
    assert "SS00076" in c.get("/api/matches").json()["matches"]
    seen = {}
    with c.websocket_connect("/ws?mode=mock&speed=60&start=85") as ws:
        while True:
            m = json.loads(ws.receive_text())
            seen[m["t"]] = seen.get(m["t"], 0) + 1
            if m["t"] in ("end", "error"):
                break
    assert seen.get("error") is None
    for kind in ("meta", "ev", "snap", "clock", "moment", "recap", "end"):
        assert seen.get(kind), kind
