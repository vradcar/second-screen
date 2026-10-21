"""Live match server: replays a synthetic match as a real-time feed and streams the
pipeline's output to the browser over a WebSocket.

    python -m secondscreen.server                 # http://localhost:8000
    python -m secondscreen.server --port 8080

Modes (query param `mode`):
  recorded  stats engine runs live; agent moments come from a recorded run (default, free)
  mock      full pipeline live with the offline mock model
  live      full pipeline live with Microsoft Foundry
Other params: match (file stem), speed (x real time), start (match minute to begin at).

Two cursors over the event list:
  animation cursor  sends events a few seconds early so the pitch can interpolate the ball
  pipeline cursor   feeds events to the stats engine / agents exactly at "now"
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

DATA = Path(os.environ.get("SECONDSCREEN_DATA", "data"))
STATIC = Path(__file__).parent / "static"
TICK = 0.1                # seconds between clock updates
LEAD = 6.0                # match seconds of events sent ahead for animation
SNAP_EVERY = 4.0          # match seconds between stats snapshots
RECORDED_LATENCY = 3.0    # wall seconds a recorded moment appears after its signal (honest-ish agent delay)

app = FastAPI(title="Second Screen")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.open(encoding="utf-8")] if path.exists() else []


def match_files() -> list[str]:
    return sorted(p.stem.removeprefix("match_") for p in DATA.glob("match_*.jsonl")
                  if p.stem.count(".") == 0)


ANIM_KEYS = ("event_id", "seq", "type", "team_id", "player_id", "player_name", "x", "y", "end_x", "end_y",
             "outcome", "recipient_id", "elapsed_seconds", "clock", "period", "distance_m", "ball_speed_kmh",
             "speed_kmh", "shot_speed_kmh", "score", "card", "player_off_id", "assist_name", "body_part", "height")


def anim_event(e: dict) -> dict:
    return {k: e[k] for k in ANIM_KEYS if k in e}


def compact_snapshot(engine) -> dict:
    snap = engine.snapshot()
    top = sorted(snap["players"], key=lambda p: -(p["goals"] * 3 + p["assists"] * 2 + p["xg"] + p["key_passes"] * 0.5))
    # Key moments from the engine's full history, so a mid-match start still shows earlier goals.
    markers = [{"kind": sg.kind, "elapsed": sg.elapsed, "clock": sg.clock, "team_id": sg.team_id,
                "label": sg.facts.get("scorer") or sg.facts.get("player") or ""}
               for sg in engine.signals if sg.kind in ("goal", "red_card")]
    return {"clock": snap["clock"], "period": snap["period"], "score": snap["score"], "teams": snap["teams"],
            "markers": markers,
            "momentum": snap["momentum"], "regime": snap["regime"], "pressing": snap["pressing"],
            "series": snap["series"][-120:],
            "players": [{k: p[k] for k in ("player_id", "name", "team_id", "goals", "assists", "xg", "shots",
                                           "touches", "distance_m", "top_speed_kmh", "on_pitch")} for p in top]}


class Session:
    def __init__(self, ws: WebSocket, match: str, mode: str, speed: float, start_min: float):
        self.ws, self.mode, self.speed = ws, mode, max(0.25, min(speed, 60.0))
        self.events = load_jsonl(DATA / f"match_{match}.jsonl")
        if not self.events:
            raise FileNotFoundError(match)
        self.match = match
        self.start_elapsed = self._elapsed_at_minute(start_min)
        self.paused = False
        self.out: asyncio.Queue = asyncio.Queue()
        self.recorded_moments = load_jsonl(DATA / f"match_{match}.moments.jsonl") if mode == "recorded" else []
        self.recorded_cues = [c for c in load_jsonl(DATA / f"match_{match}.cues.jsonl") if not c.get("moment_id")] \
            if mode == "recorded" else []
        recap = DATA / f"match_{match}.recap.json"
        self.recorded_recap = json.loads(recap.read_text(encoding="utf-8")) if mode == "recorded" and recap.exists() else None
        self.orch = self._build_orchestrator()

    def _elapsed_at_minute(self, minute: float) -> float:
        if minute <= 0:
            return 0.0
        for e in self.events:
            if (e["period"] == 2 or minute < 45) and e["clock_seconds"] >= minute * 60:
                return e["elapsed_seconds"]
        return 0.0

    def _build_orchestrator(self):
        from secondscreen.agents.llm import make_client
        from secondscreen.agents.orchestrator import MatchOrchestrator
        client = make_client("mock" if self.mode != "live" else "live")
        orch = MatchOrchestrator(client, background=True, on_moment=self._on_moment, on_cue=self._on_cue)
        orch.narrate = self.mode in ("mock", "live")
        return orch

    async def _on_moment(self, m: dict) -> None:
        if "recap" in m:
            await self.out.put({"t": "recap", "r": m["recap"]})
        else:
            await self.out.put({"t": "moment", "m": m})

    def _on_cue(self, c: dict) -> None:
        if self.mode != "recorded":
            self.out.put_nowait({"t": "cue", "c": c})

    async def send(self, msg: dict) -> None:
        await self.ws.send_text(json.dumps(msg, ensure_ascii=False, default=str))

    async def pump(self) -> None:
        while True:
            await self.send(await self.out.get())

    async def control(self) -> None:
        while True:
            msg = json.loads(await self.ws.receive_text())
            if msg.get("cmd") == "pause":
                self.paused = True
            elif msg.get("cmd") == "play":
                self.paused = False
            elif msg.get("cmd") == "speed":
                self.speed = max(0.25, min(float(msg["value"]), 60.0))
            await self.send({"t": "state", "paused": self.paused, "speed": self.speed})

    async def run(self) -> None:
        ev = self.events
        start = ev[0]
        await self.send({"t": "meta", "match_id": start["match_id"], "home": start["home"], "away": start["away"],
                         "mode": self.mode, "speed": self.speed, "duration": ev[-1]["elapsed_seconds"],
                         "start_elapsed": self.start_elapsed})
        # Fast-forward to the start point without model calls.
        narrate = self.orch.narrate
        self.orch.narrate = False
        i_proc = 0
        while i_proc < len(ev) and ev[i_proc]["elapsed_seconds"] < self.start_elapsed:
            await self.orch.ingest(ev[i_proc])
            i_proc += 1
        self.orch.narrate = narrate
        clock = self.start_elapsed
        backlog = [m for m in self.recorded_moments if m["elapsed"] < clock]
        for m in backlog:
            await self.send({"t": "moment", "m": m, "backlog": True})
        rec_m = [m for m in self.recorded_moments if m["elapsed"] >= clock]
        rec_c = [c for c in self.recorded_cues if c["elapsed"] >= clock]
        due_m: list[tuple[float, dict]] = []      # (wall time due, moment)
        i_anim, last_snap = i_proc, -1e9
        pumper = asyncio.create_task(self.pump())
        controller = asyncio.create_task(self.control())
        last = time.perf_counter()
        try:
            while i_proc < len(ev):
                await asyncio.sleep(TICK)
                now = time.perf_counter()
                if not self.paused:
                    clock += (now - last) * self.speed
                last = now
                while i_anim < len(ev) and ev[i_anim]["elapsed_seconds"] <= clock + LEAD:
                    await self.send({"t": "ev", "e": anim_event(ev[i_anim])})
                    i_anim += 1
                while i_proc < len(ev) and ev[i_proc]["elapsed_seconds"] <= clock:
                    await self.orch.ingest(ev[i_proc])
                    i_proc += 1
                while rec_c and rec_c[0]["elapsed"] <= clock:
                    await self.send({"t": "cue", "c": rec_c.pop(0)})
                while rec_m and rec_m[0]["elapsed"] <= clock:
                    due_m.append((now + RECORDED_LATENCY, rec_m.pop(0)))
                while due_m and due_m[0][0] <= now:
                    await self.send({"t": "moment", "m": due_m.pop(0)[1]})
                if clock - last_snap >= SNAP_EVERY:
                    last_snap = clock
                    await self.send({"t": "snap", "s": compact_snapshot(self.orch.engine)})
                await self.send({"t": "clock", "elapsed": round(clock, 2), "clock": self.orch.engine.clock,
                                 "period": self.orch.engine.period})
            for _, m in due_m:
                await self.send({"t": "moment", "m": m})
            await self.send({"t": "snap", "s": compact_snapshot(self.orch.engine)})
            if self.recorded_recap:
                await self.send({"t": "recap", "r": self.recorded_recap})
            await self.orch.drain()
            await asyncio.sleep(0.2)
            await self.send({"t": "end"})
            await controller
        finally:
            pumper.cancel()
            controller.cancel()
            await self.orch.close()


@app.get("/api/matches")
def matches():
    return {"matches": match_files(), "live_available": bool(os.environ.get("AZURE_OPENAI_API_KEY")
                                                             or os.environ.get("AZURE_AI_PROJECT_ENDPOINT"))}


@app.get("/api/health")
def health():
    return {"ok": True}


@app.websocket("/ws")
async def ws_match(ws: WebSocket, match: str = "SS00076", mode: str = "recorded", speed: float = 10.0,
                   start: float = 0.0):
    await ws.accept()
    if mode == "live" and not matches()["live_available"]:
        mode = "mock"
    try:
        session = Session(ws, match, mode, speed, start)
        await session.run()
    except WebSocketDisconnect:
        pass
    except FileNotFoundError:
        await ws.send_text(json.dumps({"t": "error", "message": f"no match {match}"}))
        await ws.close()


if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}")
    def index(path: str):
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
else:
    @app.get("/")
    def no_ui():
        return JSONResponse({"message": "UI not built. Run `npm run build` in web/."})
