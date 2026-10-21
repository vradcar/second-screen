"""The live match feed: a data provider publishes events as they happen; the
broadcast pipeline consumes them.

    MemoryFeed     in-process queue for local development and tests
    EventHubFeed   Azure Event Hubs, authenticated with a managed identity

Run the publisher on its own (e.g. from a laptop or a Container Apps job):

    python -m secondscreen.cloud.feed --match SS00076 --speed 5
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections.abc import AsyncIterator, Iterable
from pathlib import Path

END = {"type": "_end_of_feed"}


async def replay(events: Iterable[dict], speed: float, publish) -> None:
    """Publish events on their real timestamps, scaled by `speed`, in small batches."""
    events = list(events)
    if not events:
        return
    t0, e0 = time.perf_counter(), events[0]["elapsed_seconds"]
    batch: list[dict] = []
    for e in events:
        due = t0 + (e["elapsed_seconds"] - e0) / speed
        wait = due - time.perf_counter()
        if wait > 0.05 and batch:
            await publish(batch)
            batch = []
        if wait > 0:
            await asyncio.sleep(wait)
        batch.append(e)
    if batch:
        await publish(batch)
    await publish([END])


class MemoryFeed:
    kind = "memory"

    def __init__(self) -> None:
        self._subs: list[asyncio.Queue] = []

    async def publish(self, events: list[dict]) -> None:
        for q in self._subs:
            for e in events:
                q.put_nowait(e)

    async def subscribe(self) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._subs.append(q)
        try:
            while True:
                e = await q.get()
                yield e
                if e.get("type") == END["type"]:
                    return
        finally:
            self._subs.remove(q)

    async def close(self) -> None:
        pass


class EventHubFeed:
    """One hub, one partition (keeps match events in order)."""
    kind = "eventhubs"

    def __init__(self, namespace: str, hub: str):
        from azure.identity.aio import DefaultAzureCredential
        self.namespace, self.hub = namespace, hub
        self._cred = DefaultAzureCredential()
        self._producer = None

    async def publish(self, events: list[dict]) -> None:
        from azure.eventhub import EventData
        from azure.eventhub.aio import EventHubProducerClient
        if self._producer is None:
            self._producer = EventHubProducerClient(self.namespace, self.hub, credential=self._cred)
        batch = await self._producer.create_batch()
        for e in events:
            data = EventData(json.dumps(e, separators=(",", ":")))
            try:
                batch.add(data)
            except ValueError:            # batch full: send and start another
                await self._producer.send_batch(batch)
                batch = await self._producer.create_batch()
                batch.add(data)
        await self._producer.send_batch(batch)

    async def subscribe(self) -> AsyncIterator[dict]:
        from azure.eventhub.aio import EventHubConsumerClient
        q: asyncio.Queue = asyncio.Queue()
        consumer = EventHubConsumerClient(self.namespace, self.hub, consumer_group="$Default", credential=self._cred)

        async def on_event(_ctx, ev):
            if ev is not None:
                q.put_nowait(json.loads(ev.body_as_str()))

        task = asyncio.create_task(consumer.receive(on_event, starting_position="@latest", max_wait_time=1))
        try:
            while True:
                e = await q.get()
                yield e
                if e.get("type") == END["type"]:
                    return
        finally:
            task.cancel()
            await consumer.close()

    async def close(self) -> None:
        if self._producer:
            await self._producer.close()
        await self._cred.close()


def make_feed():
    ns, hub = os.environ.get("EVENTHUB_NAMESPACE"), os.environ.get("EVENTHUB_NAME", "match-events")
    return EventHubFeed(ns, hub) if ns else MemoryFeed()


def load_events(match: str, data_dir: str | Path = "data") -> list[dict]:
    path = Path(data_dir) / f"match_{match}.jsonl"
    return [json.loads(line) for line in path.open(encoding="utf-8")]


async def _main(args) -> None:
    feed = make_feed()
    if feed.kind == "memory":
        raise SystemExit("Set EVENTHUB_NAMESPACE (e.g. myns.servicebus.windows.net) to publish to Event Hubs.")
    events = load_events(args.match, args.data)
    print(f"Publishing {len(events)} events from {args.match} to {feed.namespace}/{feed.hub} at {args.speed}x")
    await replay(events, args.speed, feed.publish)
    await feed.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="secondscreen.cloud.feed")
    ap.add_argument("--match", default="SS00076")
    ap.add_argument("--speed", type=float, default=5.0)
    ap.add_argument("--data", default="data")
    asyncio.run(_main(ap.parse_args()))
