"""Chat clients for the agents.

- live:   Microsoft Foundry project (Entra ID auth via `az login` / managed identity),
          or Azure OpenAI with an API key
- mock:   deterministic offline model, so tests and CI never need the network
- record: live, saving every response to a JSONL cache
- replay: serve responses from that cache (reliable demos, zero cost)

All of them are Agent Framework chat clients, so the agents don't know which one they have.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from agent_framework import BaseChatClient, ChatResponse, Message

class _NoToolWarning(logging.Filter):
    """Our agents use structured output, not tools, so this framework warning is noise."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "does not support function invoking" not in record.getMessage()


logging.getLogger("agent_framework").addFilter(_NoToolWarning())

ROLE_RE = re.compile(r"ROLE:\s*(\w+)")
JSON_BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


def _text_of(messages) -> str:
    parts = []
    for m in messages:
        t = getattr(m, "text", None)
        parts.append(t if t is not None else str(m))
    return "\n".join(parts)


class MockChatClient(BaseChatClient):
    """Offline stand-in that answers in each agent's schema using the deterministic
    templates. `inject_error_every` makes the analyst occasionally invent a number,
    to exercise the fact-check → revise loop."""

    OTEL_PROVIDER_NAME = "mock"

    def __init__(self, inject_error_every: int = 0, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.inject_error_every = inject_error_every
        self.calls: dict[str, int] = {}

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        from secondscreen.agents import mock_brain

        text = _text_of(messages) + "\n" + str(options.get("instructions", ""))
        role = (ROLE_RE.search(text) or [None, "unknown"])[1]
        payload = json.loads(JSON_BLOCK.search(text).group(1)) if JSON_BLOCK.search(text) else {}
        n = self.calls[role] = self.calls.get(role, 0) + 1
        out = mock_brain.respond(role, payload, n, self.inject_error_every)
        return ChatResponse(messages=[Message(role="assistant", contents=[json.dumps(out)])],
                            response_id=f"mock-{role}-{n}")


class CachingChatClient(BaseChatClient):
    """Record/replay wrapper around any chat client, keyed by prompt + schema."""

    OTEL_PROVIDER_NAME = "cache"

    def __init__(self, inner: Any | None, path: str | Path, mode: str = "record", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.inner, self.path, self.mode = inner, Path(path), mode
        self.cache: dict[str, str] = {}
        self.hits = self.misses = 0
        if self.path.exists():
            for line in self.path.open(encoding="utf-8"):
                row = json.loads(line)
                self.cache[row["key"]] = row["text"]

    @staticmethod
    def key(messages, options) -> str:
        fmt = options.get("response_format")
        raw = json.dumps({"m": _text_of(messages), "i": str(options.get("instructions", "")),
                          "f": getattr(fmt, "__name__", str(fmt))}, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()[:24]

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        k = self.key(messages, options)
        if k in self.cache:
            self.hits += 1
            return ChatResponse(messages=[Message(role="assistant", contents=[self.cache[k]])], response_id=f"cache-{k}")
        if self.mode == "replay" or self.inner is None:
            raise LookupError(f"cache miss {k} in replay mode")
        self.misses += 1
        resp = await self.inner.get_response(messages, options=options)
        text = resp.text
        self.cache[k] = text
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"key": k, "text": text}) + "\n")
        return ChatResponse(messages=[Message(role="assistant", contents=[text])], response_id=f"rec-{k}")


def live_client():
    """Foundry project client if configured, else Azure OpenAI with a key."""
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT", "gpt-4.1-mini")
    if os.environ.get("AZURE_OPENAI_API_KEY") and os.environ.get("AZURE_OPENAI_ENDPOINT"):
        from agent_framework.openai import OpenAIChatCompletionClient
        return OpenAIChatCompletionClient(
            model=deployment, api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-10-21"))
    if os.environ.get("AZURE_AI_PROJECT_ENDPOINT"):
        from agent_framework.foundry import FoundryChatClient
        from azure.identity.aio import DefaultAzureCredential
        return FoundryChatClient(project_endpoint=os.environ["AZURE_AI_PROJECT_ENDPOINT"],
                                 model=deployment, credential=DefaultAzureCredential())
    raise RuntimeError("Set AZURE_AI_PROJECT_ENDPOINT (with az login) or AZURE_OPENAI_ENDPOINT + "
                       "AZURE_OPENAI_API_KEY. See .env.example.")


def load_dotenv(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def make_client(mode: str, cache_path: str | Path = "data/llm_cache.jsonl", inject_error_every: int = 0):
    if mode == "mock":
        return MockChatClient(inject_error_every=inject_error_every)
    if mode == "live":
        return live_client()
    if mode == "record":
        return CachingChatClient(live_client(), cache_path, mode="record")
    if mode == "replay":
        return CachingChatClient(None, cache_path, mode="replay")
    raise ValueError(mode)
