"""Run the full agent pipeline over a match.

    python -m secondscreen.agents data/match_SS00076.jsonl --mode mock
    python -m secondscreen.agents data/match_SS00076.jsonl --mode record   # live Foundry, saves cache
    python -m secondscreen.agents data/match_SS00076.jsonl --mode replay   # from cache, no network
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from secondscreen.agents.llm import describe_backend, load_dotenv, make_client
from secondscreen.agents.orchestrator import MatchOrchestrator


async def run(args) -> None:
    load_dotenv()
    client = make_client(args.mode, args.cache, inject_error_every=args.inject_errors)
    if args.mode in ("live", "record"):
        print("Backend:", describe_backend(), flush=True)
    orch = MatchOrchestrator(client, use_judge=not args.no_judge)

    async def show(m):
        flag = {"agent": "  ", "fallback": "FB"}[m["source"]]
        print(f"{m['clock']:>7} {flag} x{m['attempts']} {m['kind']:<18} {m['draft']['headline']}", flush=True)
        # Fail fast: if the first moments all fell back because the model errored, stop and say why.
        ms = orch.store.moments
        if args.mode in ("live", "record") and len(ms) == 3 and all(x["source"] == "fallback" for x in ms):
            errors = [e["error"] for x in ms for e in x["check_log"] if "error" in e]
            if errors:
                raise SystemExit(f"\nModel calls are failing, stopping early.\nFirst error: {errors[0]}\n"
                                 "Run `python -m secondscreen.agents.doctor` for a diagnosis.")

    orch.on_moment = show
    t0 = time.perf_counter()
    for line in Path(args.path).open(encoding="utf-8"):
        await orch.ingest(json.loads(line))
    st = orch.store
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    mid = st.match_id
    for name, rows in (("moments", st.moments), ("cues", sorted(st.cues, key=lambda c: c["elapsed"])),
                       ("audit", st.audit)):
        with (out / f"match_{mid}.{name}.jsonl").open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
    if st.recap:
        (out / f"match_{mid}.recap.json").write_text(json.dumps(st.recap, indent=1, ensure_ascii=False), encoding="utf-8")
        print("\n" + st.recap["recap"]["title"])
        print(st.recap["recap"]["standfirst"])
    summary = orch.summary() | {"wall_seconds": round(time.perf_counter() - t0, 1), "mode": args.mode}
    if hasattr(client, "hits"):
        summary |= {"cache_hits": client.hits, "cache_misses": client.misses}
    print("\n" + json.dumps(summary, indent=1))


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_console()
    ap = argparse.ArgumentParser(prog="secondscreen.agents")
    ap.add_argument("path")
    ap.add_argument("--mode", choices=["mock", "live", "record", "replay"], default="mock")
    ap.add_argument("--cache", default="data/llm_cache.jsonl")
    ap.add_argument("--out", default="data")
    ap.add_argument("--no-judge", action="store_true", help="skip the LLM judge (rules-only fact check)")
    ap.add_argument("--inject-errors", type=int, default=0,
                    help="mock only: every Nth analyst draft invents a number, to demo the revise loop")
    asyncio.run(run(ap.parse_args()))


if __name__ == "__main__":
    main()
