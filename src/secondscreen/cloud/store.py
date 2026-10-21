"""Shared state for a broadcast: published moments, overlay cues and the recap.

The agents coordinate through this store (the story so far, what's already on air),
and late-joining viewers get their backlog from it.

    MemoryStore   local development and tests
    CosmosStore   Azure Cosmos DB (serverless), authenticated with a managed identity
"""
from __future__ import annotations

import os
from typing import Protocol


class Store(Protocol):
    async def save_moment(self, run_id: str, moment: dict) -> None: ...
    async def save_cue(self, run_id: str, cue: dict) -> None: ...
    async def save_run(self, run_id: str, doc: dict) -> None: ...
    async def moments(self, run_id: str) -> list[dict]: ...
    async def cues(self, run_id: str) -> list[dict]: ...
    async def run(self, run_id: str) -> dict | None: ...
    async def close(self) -> None: ...


class MemoryStore:
    kind = "memory"

    def __init__(self) -> None:
        self._m: dict[str, list[dict]] = {}
        self._c: dict[str, list[dict]] = {}
        self._r: dict[str, dict] = {}

    async def save_moment(self, run_id: str, moment: dict) -> None:
        self._m.setdefault(run_id, []).append(moment)

    async def save_cue(self, run_id: str, cue: dict) -> None:
        self._c.setdefault(run_id, []).append(cue)

    async def save_run(self, run_id: str, doc: dict) -> None:
        self._r[run_id] = {**self._r.get(run_id, {}), **doc}

    async def moments(self, run_id: str) -> list[dict]:
        return list(self._m.get(run_id, []))

    async def cues(self, run_id: str) -> list[dict]:
        return list(self._c.get(run_id, []))

    async def run(self, run_id: str) -> dict | None:
        return self._r.get(run_id)

    async def close(self) -> None:
        pass


class CosmosStore:
    """Containers (all partitioned on /run_id): moments, cues, runs."""
    kind = "cosmos"

    def __init__(self, endpoint: str, database: str = "secondscreen"):
        from azure.cosmos.aio import CosmosClient
        from azure.identity.aio import DefaultAzureCredential
        self._cred = DefaultAzureCredential()
        self._client = CosmosClient(endpoint, credential=self._cred)
        self._db = self._client.get_database_client(database)
        self._moments = self._db.get_container_client("moments")
        self._cues = self._db.get_container_client("cues")
        self._runs = self._db.get_container_client("runs")

    async def save_moment(self, run_id: str, moment: dict) -> None:
        await self._moments.upsert_item({**moment, "id": moment["moment_id"], "run_id": run_id})

    async def save_cue(self, run_id: str, cue: dict) -> None:
        await self._cues.upsert_item({**cue, "id": cue["cue_id"], "run_id": run_id})

    async def save_run(self, run_id: str, doc: dict) -> None:
        current = await self.run(run_id) or {}
        await self._runs.upsert_item({**current, **doc, "id": run_id, "run_id": run_id})

    async def _query(self, container, run_id: str) -> list[dict]:
        items = container.query_items("SELECT * FROM c WHERE c.run_id = @r ORDER BY c.elapsed",
                                      parameters=[{"name": "@r", "value": run_id}], partition_key=run_id)
        return [i async for i in items]

    async def moments(self, run_id: str) -> list[dict]:
        return await self._query(self._moments, run_id)

    async def cues(self, run_id: str) -> list[dict]:
        return await self._query(self._cues, run_id)

    async def run(self, run_id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError
        try:
            return await self._runs.read_item(run_id, partition_key=run_id)
        except CosmosResourceNotFoundError:
            return None

    async def close(self) -> None:
        await self._client.close()
        await self._cred.close()


def make_store() -> Store:
    endpoint = os.environ.get("COSMOS_ENDPOINT")
    return CosmosStore(endpoint, os.environ.get("COSMOS_DATABASE", "secondscreen")) if endpoint else MemoryStore()
