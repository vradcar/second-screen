"""On air: one shared live broadcast that every viewer joins.

    data provider ──publish──► live feed (Event Hubs) ──consume──► Broadcast ──fan-out──► every viewer
                                                                       │
                                                         stats engine + agents (once, shared)
                                                                       │
                                                                 store (Cosmos DB)

Events are fanned out to viewers as soon as they arrive (so the pitch can animate
ahead), and enter the pipeline after a short broadcast delay of LEAD match seconds,
the way TV runs a few seconds behind the stadium. Viewers who join late get the
backlog (moments, cues) from the store.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

LEAD = 6.0
TICK = 0.1
SNAP_EVERY = 4.0
RECORDED_LATENCY = 3.0
NOMINAL_DURATION = 5760.0     # 96 minutes; the real length isn't known until full time


class Broadcast:
    def __init__(self, feed, store, data_dir: Path, snapshot_fn, anim_fn):
        self.feed, self.store, self.data_dir = feed, store, data_dir
        self.snapshot_fn, self.anim_fn = snapshot_fn, anim_fn
        self.state = "idle"
        self.run_id: str | None = None
        self.match = None
        self.speed = 5.0
        self.agents = "mock"
        self.subscribers: set[asyncio.Queue] = set()
        self.tasks: list[asyncio.Task] = []
        self._reset()

    def _reset(self) -> None:
        self.events: list[dict] = []
        self.meta: dict | None = None
        self.air_clock = 0.0
        self.feed_done = False
        self.orch = None
        self.last_snap: dict | None = None
        self.started_wall: float | None = None

    # ---------------------------------------------------------------- viewers
    def status(self) -> dict:
        return {"state": self.state, "run_id": self.run_id, "match": self.match, "speed": self.speed,
                "agents": self.agents, "viewers": len(self.subscribers), "feed": self.feed.kind,
                "store": self.store.kind, "clock": self.orch.engine.clock if self.orch else None}

    def _fan_out(self, msg: dict) -> None:
        for q in list(self.subscribers):
            q.put_nowait(msg)

    async def join(self) -> asyncio.Queue:
        """Register a viewer and queue up everything they need to catch up."""
        q: asyncio.Queue = asyncio.Queue()
        if self.state == "idle" or not self.meta:
            q.put_nowait({"t": "idle", "status": self.status()})
        else:
            q.put_nowait({**self.meta, "start_elapsed": self.air_clock})
            if self.last_snap:
                q.put_nowait({"t": "snap", "s": self.last_snap})
            for m in await self.store.moments(self.run_id):
                q.put_nowait({"t": "moment", "m": m, "backlog": True})
            for c in await self.store.cues(self.run_id):
                q.put_nowait({"t": "cue", "c": c})
            for e in self.events:
                if e["elapsed_seconds"] >= self.air_clock - 2:
                    q.put_nowait({"t": "ev", "e": self.anim_fn(e)})
            if self.state == "ended":
                run = await self.store.run(self.run_id) or {}
                if run.get("recap"):
                    q.put_nowait({"t": "recap", "r": run["recap"]})
                q.put_nowait({"t": "end"})
        self.subscribers.add(q)
        return q

    def leave(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    # -------------------------------------------------------------- lifecycle
    async def start(self, match: str, speed: float, agents: str, publish: bool = True) -> dict:
        if self.state == "on_air":
            return self.status()
        await self.stop()
        self._reset()
        max_speed = float(os.environ.get("SECONDSCREEN_MAX_SPEED", "40"))
        self.state, self.match, self.speed, self.agents = "on_air", match, max(1.0, min(speed, max_speed)), agents
        self.run_id = f"{match}-{int(time.time())}"
        self.orch = self._build_orchestrator()
        await self.store.save_run(self.run_id, {"match": match, "speed": self.speed, "agents": agents,
                                                "state": "on_air", "started": time.time()})
        self.tasks = [asyncio.create_task(self._consume()), asyncio.create_task(self._air())]
        if publish:
            from secondscreen.cloud.feed import load_events, replay
            events = load_events(match, self.data_dir)
            await asyncio.sleep(1.0)       # give the consumer a moment to attach
            self.tasks.append(asyncio.create_task(replay(events, self.speed, self.feed.publish)))
        return self.status()

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        self.tasks = []
        if self.orch:
            await self.orch.close()
        if self.state == "on_air":
            self.state = "ended"

    def _build_orchestrator(self):
        from secondscreen.agents.llm import make_client
        from secondscreen.agents.orchestrator import MatchOrchestrator
        client = make_client("live" if self.agents == "live" else "mock")
        orch = MatchOrchestrator(client, background=True, on_moment=self._on_moment, on_cue=self._on_cue)
        orch.narrate = self.agents in ("live", "mock")
        return orch

    async def _on_moment(self, m: dict) -> None:
        if "recap" in m:
            await self.store.save_run(self.run_id, {"recap": m["recap"]})
            self._fan_out({"t": "recap", "r": m["recap"]})
        else:
            await self.store.save_moment(self.run_id, m)
            self._fan_out({"t": "moment", "m": m})

    def _on_cue(self, c: dict) -> None:
        if self.agents != "recorded":
            asyncio.create_task(self.store.save_cue(self.run_id, c))
            self._fan_out({"t": "cue", "c": c})

    # ----------------------------------------------------------------- loops
    async def _consume(self) -> None:
        async for e in self.feed.subscribe():
            if e.get("type") == "_end_of_feed":
                self.feed_done = True
                return
            self.events.append(e)
            if e["type"] == "match_start":
                self.meta = {"t": "meta", "match_id": e["match_id"], "home": e["home"], "away": e["away"],
                             "mode": "onair", "speed": self.speed, "duration": NOMINAL_DURATION,
                             "start_elapsed": e["elapsed_seconds"], "periods": [], "chapters": [],
                             "run_id": self.run_id}
                self._fan_out(self.meta)
            if self.started_wall is None:
                self.started_wall, self.first_elapsed = time.perf_counter(), e["elapsed_seconds"]
            self._fan_out({"t": "ev", "e": self.anim_fn(e)})

    async def _air(self) -> None:
        """Feed the pipeline at broadcast time (LEAD seconds behind the feed)."""
        rec_m, rec_c, rec_recap = self._recorded()
        due: list[tuple[float, dict]] = []
        i, last_snap = 0, -1e9
        while True:
            await asyncio.sleep(TICK)
            if self.started_wall is None:
                continue
            now = time.perf_counter()
            self.air_clock = self.first_elapsed + (now - self.started_wall) * self.speed - LEAD
            while i < len(self.events) and self.events[i]["elapsed_seconds"] <= self.air_clock:
                await self.orch.ingest(self.events[i])
                i += 1
            while rec_c and rec_c[0]["elapsed"] <= self.air_clock:
                c = rec_c.pop(0)
                await self.store.save_cue(self.run_id, c)
                self._fan_out({"t": "cue", "c": c})
            while rec_m and rec_m[0]["elapsed"] <= self.air_clock:
                due.append((now + RECORDED_LATENCY, rec_m.pop(0)))
            while due and due[0][0] <= now:
                await self._on_moment(due.pop(0)[1])
            if self.orch.engine.home and self.air_clock - last_snap >= SNAP_EVERY:
                last_snap = self.air_clock
                self.last_snap = self.snapshot_fn(self.orch.engine)
                self._fan_out({"t": "snap", "s": self.last_snap})
            if self.orch.engine.home:
                self._fan_out({"t": "clock", "elapsed": round(self.air_clock, 2), "clock": self.orch.engine.clock,
                               "period": self.orch.engine.period})
            if self.feed_done and i >= len(self.events):
                break
        for _, m in due:
            await self._on_moment(m)
        await self.orch.drain()
        if rec_recap:
            await self._on_moment({"recap": rec_recap})
        self.last_snap = self.snapshot_fn(self.orch.engine)
        self._fan_out({"t": "snap", "s": self.last_snap})
        self.state = "ended"
        await self.store.save_run(self.run_id, {"state": "ended", "final_score": self.orch.engine.score})
        self._fan_out({"t": "end"})

    def _recorded(self):
        if self.agents != "recorded":
            return [], [], None
        d = self.data_dir
        load = lambda p: [json.loads(x) for x in p.open(encoding="utf-8")] if p.exists() else []  # noqa: E731
        from secondscreen.server.app import with_commentary
        moments = with_commentary(load(d / f"match_{self.match}.moments.jsonl"), d / f"match_{self.match}.commentary.jsonl")
        cues = [c for c in load(d / f"match_{self.match}.cues.jsonl") if not c.get("moment_id")]
        recap_p = d / f"match_{self.match}.recap.json"
        recap = json.loads(recap_p.read_text(encoding="utf-8")) if recap_p.exists() else None
        return moments, cues, recap
