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

from contextlib import asynccontextmanager  # noqa: E402

from fastapi import HTTPException  # noqa: E402

from secondscreen.cloud.feed import make_feed  # noqa: E402
from secondscreen.cloud.store import make_store  # noqa: E402
from secondscreen.cloud.translate import Translator  # noqa: E402

BROADCAST_AGENTS = os.environ.get("BROADCAST_AGENTS", "recorded")   # recorded | mock | live
START_TOKEN = os.environ.get("BROADCAST_START_TOKEN")               # optional: protect start/stop


@asynccontextmanager
async def lifespan(app: FastAPI):
    from secondscreen.server.broadcast import Broadcast
    from secondscreen.telemetry import setup_tracing
    setup_tracing("second-screen-server")
    app.state.translator = Translator()
    app.state.broadcast = Broadcast(make_feed(), make_store(), DATA, compact_snapshot, anim_event)
    yield
    await app.state.broadcast.stop()
    await app.state.broadcast.feed.close()
    await app.state.broadcast.store.close()


app = FastAPI(title="Second Screen", lifespan=lifespan)


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
    def __init__(self, ws: WebSocket, match: str, mode: str, speed: float, start_min: float, at: float = -1.0):
        self.ws, self.mode, self.speed = ws, mode, max(0.25, min(speed, 60.0))
        self.events = load_jsonl(DATA / f"match_{match}.jsonl")
        if not self.events:
            raise FileNotFoundError(match)
        self.match = match
        # `at` (elapsed seconds) is a precise seek from the timeline; `start` is a match minute.
        duration = self.events[-1]["elapsed_seconds"]
        self.start_elapsed = min(max(at, 0.0), duration - 1) if at >= 0 else self._elapsed_at_minute(start_min)
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
        periods = [{"period": e["period"], "elapsed": e["elapsed_seconds"], "clock_seconds": e["clock_seconds"]}
                   for e in ev if e["type"] == "period_start"]
        # Timeline chapters: where the goals and red cards are, for jumping straight to them.
        chapters = [{"kind": "goal" if e["type"] == "goal" else "red_card", "elapsed": e["elapsed_seconds"],
                     "clock": e["clock"], "team_id": e.get("team_id"), "label": e.get("player_name", "")}
                    for e in ev if e["type"] == "goal" or (e["type"] == "card" and e.get("card") == "second_yellow")]
        await self.send({"t": "meta", "match_id": start["match_id"], "home": start["home"], "away": start["away"],
                         "mode": self.mode, "speed": self.speed, "duration": ev[-1]["elapsed_seconds"],
                         "start_elapsed": self.start_elapsed, "periods": periods, "chapters": chapters})
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


def _model_configured() -> bool:
    return bool(os.environ.get("AZURE_OPENAI_API_KEY") or os.environ.get("AZURE_AI_PROJECT_ENDPOINT")
                or os.environ.get("AZURE_USE_IDENTITY"))


# On a public deployment, live model calls cost money per viewer; keep them opt-in.
PUBLIC_LIVE = os.environ.get("ALLOW_PUBLIC_LIVE", "1" if not os.environ.get("CONTAINER_APP_NAME") else "0") == "1"


@app.get("/api/matches")
def matches():
    return {"matches": match_files(), "live_available": _model_configured() and PUBLIC_LIVE,
            "start_protected": bool(START_TOKEN), "translate": _translator().status()}


def _translator() -> Translator:
    if not hasattr(app.state, "translator"):
        app.state.translator = Translator()
    return app.state.translator


@app.post("/api/translate")
async def translate(body: dict):
    """{texts: [...], to: "de", from?: "es"} -> {items: [{text, ok, why?}]}. Azure AI Translator,
    cached, budgeted, and number-checked against the original."""
    texts = body.get("texts")
    if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
        raise HTTPException(status_code=400, detail="texts must be a list of strings")
    try:
        items = await _translator().translate(texts, str(body.get("to", "")), body.get("from"))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"items": items}


@app.get("/api/health")
def health():
    return {"ok": True}


def _check_token(token: str | None) -> None:
    if START_TOKEN and token != START_TOKEN:
        raise HTTPException(status_code=403, detail="This broadcast is protected. Pass ?token=...")


@app.get("/api/broadcast")
def broadcast_status():
    return app.state.broadcast.status()


@app.post("/api/broadcast/start")
async def broadcast_start(match: str = "SS00076", speed: float = 5.0, agents: str | None = None,
                          publish: bool = True, token: str | None = None):
    """Start the shared live broadcast. With publish=false, an external publisher
    (python -m secondscreen.cloud.feed) supplies the events."""
    _check_token(token)
    if not (DATA / f"match_{match}.jsonl").exists():
        raise HTTPException(status_code=404, detail=f"no match {match}")
    agents = agents or BROADCAST_AGENTS
    # Live agents on a broadcast need the model configured, and the start token if one is set.
    if agents == "live" and not (_model_configured() and (PUBLIC_LIVE or (START_TOKEN and token == START_TOKEN))):
        agents = "recorded"
    return await app.state.broadcast.start(match, speed, agents, publish=publish)


@app.post("/api/broadcast/stop")
async def broadcast_stop(token: str | None = None):
    _check_token(token)
    await app.state.broadcast.stop()
    return app.state.broadcast.status()


@app.websocket("/ws/broadcast")
async def ws_broadcast(ws: WebSocket):
    await ws.accept()
    hub = app.state.broadcast
    q = await hub.join()

    async def writer():
        while True:
            await ws.send_text(json.dumps(await q.get(), ensure_ascii=False, default=str))

    w = asyncio.create_task(writer())
    try:
        while True:
            await ws.receive_text()      # viewers don't control the broadcast; keep the socket open
    except WebSocketDisconnect:
        pass
    finally:
        w.cancel()
        hub.leave(q)


@app.websocket("/ws")
async def ws_match(ws: WebSocket, match: str = "SS00076", mode: str = "recorded", speed: float = 10.0,
                   start: float = 0.0, at: float = -1.0):
    await ws.accept()
    if mode == "live" and not matches()["live_available"]:
        mode = "mock"
    try:
        session = Session(ws, match, mode, speed, start, at)
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
