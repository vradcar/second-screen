"""One live test call, with a plain-English diagnosis if it fails.

    python -m secondscreen.agents.doctor
"""
from __future__ import annotations

import asyncio
import sys
import time

from agent_framework import Agent

from secondscreen.agents.llm import _env, describe_backend, live_client, load_dotenv
from secondscreen.agents.schemas import MomentDraft

HINTS = [
    ("401", "The key was rejected. Re-copy key1 from Cloud Shell into AZURE_OPENAI_API_KEY (no quotes, no spaces)."),
    ("Access denied", "The key was rejected. Re-copy key1 from Cloud Shell into AZURE_OPENAI_API_KEY."),
    ("DeploymentNotFound", "The deployment name is wrong. AZURE_OPENAI_DEPLOYMENT should be gpt-4.1-mini."),
    ("404", "Wrong endpoint or deployment. Use https://<resource>.openai.azure.com/ and deployment gpt-4.1-mini."),
    ("429", "Rate limited. Wait a minute, or raise the deployment's tokens-per-minute in the Foundry portal."),
    ("getaddrinfo", "The endpoint host doesn't resolve. Check AZURE_OPENAI_ENDPOINT for typos or a leftover <resource>."),
    ("Name or service not known", "The endpoint host doesn't resolve. Check AZURE_OPENAI_ENDPOINT."),
    ("ConnectError", "Can't reach the endpoint. Check the URL and your network/VPN."),
    ("Connection error", "Can't reach the endpoint. Check AZURE_OPENAI_ENDPOINT (https://secondscreen-ai-ae9ze.openai.azure.com/) and your network/VPN."),
    ("CredentialUnavailable", "Entra auth isn't set up. Use the API key, or run `az login` first."),
    ("DefaultAzureCredential failed", "No Azure login on this machine. Easiest fix: set AZURE_OPENAI_ENDPOINT and "
     "AZURE_OPENAI_API_KEY in .env so the key route is used instead."),
    ("PermissionDenied", "Your account lacks the Foundry User role. Run infra/grant-access.sh in Cloud Shell."),
    ("403", "Permission denied. With az login you need the Foundry User role (infra/grant-access.sh)."),
]


async def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv()
    print("Backend:", describe_backend())
    for name in ("AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_DEPLOYMENT", "AZURE_AI_PROJECT_ENDPOINT"):
        v = _env(name)
        shown = "missing / placeholder" if not v else (f"set ({len(v)} chars)" if "KEY" in name else v)
        print(f"  {name:<26} {shown}")
    if _env("AZURE_AI_PROJECT_ENDPOINT") and ".openai.azure.com" in _env("AZURE_AI_PROJECT_ENDPOINT"):
        print("  ! AZURE_AI_PROJECT_ENDPOINT holds the OpenAI URL. That URL belongs in AZURE_OPENAI_ENDPOINT.")
    try:
        client = live_client()
    except Exception as e:  # noqa: BLE001
        print("FAIL:", e)
        return 1
    agent = Agent(client, "Reply with a tiny moment card about a test.", name="doctor")
    t0 = time.perf_counter()
    try:
        r = await agent.run('Fact: signal.kind = "test". Cite it.', options={"response_format": MomentDraft})
        v = r.value if isinstance(r.value, MomentDraft) else MomentDraft.model_validate_json(r.text)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        print("FAIL:", msg[:600])
        for needle, hint in HINTS:
            if needle in msg:
                print("FIX: ", hint)
                break
        return 1
    print(f"OK in {time.perf_counter() - t0:.1f}s -> {v.headline!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
