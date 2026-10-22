"""One command: any match -> a demo-ready recorded broadcast with commentary.

    python -m secondscreen.produce --seed 123              # simulate seed 123 and produce it
    python -m secondscreen.produce --best-of 200           # find the most dramatic of 200 seeds
    python -m secondscreen.produce --match data/match_SS00076.jsonl
    python -m secondscreen.produce --seed 123 --serve      # ...then open it in the browser

Steps (each skipped if it can't run, and you're told why):
  1. match         simulate it (or use the events file you gave)
  2. agents        analyst -> fact-checker -> personas -> commentator, on Foundry if .env has
                   credentials (recorded to the cache), else the offline mock model
  3. commentary    play-by-play + co-commentator script for every big moment (en/es/fr)
  4. translations  Azure AI Translator cache for the phones' language picker
  5. voice         Azure AI Speech audio for the commentary box
Then it prints the link: the highlights reel with commentary for that match.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path


def _say(step: str, msg: str) -> None:
    print(f"\n== {step}: {msg}", flush=True)


def resolve_match(args, data: Path) -> Path:
    from secondscreen.simulator.cli import drama_score, write_match
    from secondscreen.simulator import simulate
    if args.match:
        p = Path(args.match)
        if not p.exists():
            raise SystemExit(f"No match file at {p}")
        _say("match", f"using {p}")
        return p
    seed = args.seed
    if seed is None:
        _say("match", f"scanning {args.best_of} seeds from {args.start} for the most dramatic game")
        best = max(((drama_score(simulate(s)[1])[0], s) for s in range(args.start, args.start + args.best_of)))
        seed = best[1]
        print(f"   picked seed {seed} (drama {best[0]:.1f})")
    path = data / f"match_SS{seed:05d}.jsonl"
    if path.exists() and not args.fresh:
        _say("match", f"seed {seed} already simulated: {path}")
        return path
    ev, _, truth = write_match(seed, data)
    _say("match", f"seed {seed} -> {ev}")
    fs = truth["final_score"]
    print("   final score: " + " ".join(f"{k} {v}" for k, v in fs.items()))
    for a in truth["arcs"]:
        print(f"   hidden story: {a['description']} ({a['start_min']:.0f}'-{a['end_min']:.0f}')")
    return path


def model_configured() -> bool:
    from secondscreen.agents.llm import _env
    return bool((_env("AZURE_OPENAI_API_KEY") and _env("AZURE_OPENAI_ENDPOINT")) or _env("AZURE_AI_PROJECT_ENDPOINT")
                or (_env("AZURE_USE_IDENTITY") and _env("AZURE_OPENAI_ENDPOINT")))


async def produce(args) -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    data = Path(args.out)
    data.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    events = resolve_match(args, data)
    first = json.loads(events.open(encoding="utf-8").readline())
    mid = first["match_id"]
    prefix = data / f"match_{mid}"

    # 2. agents (the workflow includes the commentator)
    mode = args.mode if args.mode != "auto" else ("record" if model_configured() else "mock")
    moments_path = prefix.with_suffix(".moments.jsonl")
    if args.skip_agents and moments_path.exists():
        _say("agents", f"skipped, using {moments_path}")
    else:
        why = "Foundry model, recorded to the cache" if mode == "record" else (
            "offline mock model (no Azure credentials in .env)" if mode == "mock" else mode)
        _say("agents", f"running the moment workflow: {why}")
        from secondscreen.agents.__main__ import run
        await run(argparse.Namespace(path=str(events), mode=mode, cache=args.cache, out=str(data),
                                     no_judge=args.no_judge, inject_errors=0))

    # 3. commentary: written by the workflow; older runs get it written now
    from secondscreen.agents.commentary import SPOKEN, batch
    moments = [json.loads(x) for x in moments_path.open(encoding="utf-8")]
    big = [m for m in moments if m["kind"] in SPOKEN]
    if big and all(m.get("commentary") for m in big):
        _say("commentary", f"{len(big)} big moments scripted by the commentator agent")
    else:
        _say("commentary", "writing the script for a run recorded before the commentator existed")
        await batch(prefix, mode if mode != "replay" else "template")
    sample = next((m for m in big if m["kind"] == "goal" and m.get("commentary")), None)
    if sample:
        c = sample["commentary"]["en"]
        print(f"   {sample['clock']}  {c['build']}  {c['peak'].upper()}  {c['after']}")
        print(f"          pundit: {c['pundit']}")

    # 4. translations
    from secondscreen.cloud.translate import Translator
    tr = Translator()
    if args.no_translate:
        _say("translations", "skipped (--no-translate)")
    elif not tr.live:
        _say("translations", "skipped: Translator isn't configured (needs the Foundry key + endpoint in .env)")
    else:
        from secondscreen.cloud.translate import prefill as tr_prefill
        langs = [x for x in args.translate.split(",") if x]
        _say("translations", f"{', '.join(langs)} via Azure AI Translator")
        await tr_prefill(prefix, langs)

    # 5. voice
    from secondscreen.cloud.speech import Speech, voice_for
    sp = Speech()
    if args.no_voice:
        _say("voice", "skipped (--no-voice)")
    elif not sp.live:
        _say("voice", "skipped: Speech isn't configured (needs the Foundry key in .env). The commentary box "
                      "will show captions only.")
    else:
        from secondscreen.cloud.speech import prefill as sp_prefill
        _say("voice", f"Azure AI Speech: {voice_for('commentator', 'en')} + {voice_for('pundit', 'en')}")
        await sp_prefill(prefix, [x for x in args.voice_langs.split(",") if x])

    from secondscreen.highlights import pick
    clips = pick(moments)
    url = f"http://localhost:{args.port}/?match={mid}&reel=1"
    _say("done", f"{mid} in {time.perf_counter() - t0:.0f}s: {len(moments)} moments, {len(big)} with commentary, "
                 f"{len(clips)} highlights")
    print(f"   Watch: {url}   (turn Commentary on for the voices)")
    if args.serve:
        import uvicorn
        print(f"   Serving on http://localhost:{args.port} ... Ctrl+C to stop")
        config = uvicorn.Config("secondscreen.server.app:app", host="127.0.0.1", port=args.port, log_level="warning")
        await uvicorn.Server(config).serve()
    else:
        print("   Start the app with: python -m secondscreen.server")


def main() -> None:
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="secondscreen.produce", description=__doc__.split("\n\n")[0])
    which = ap.add_mutually_exclusive_group()
    which.add_argument("--seed", type=int, help="simulate this seed")
    which.add_argument("--match", help="an existing events file, e.g. data/match_SS00076.jsonl")
    which.add_argument("--best-of", type=int, default=100, help="scan this many seeds and take the most dramatic")
    ap.add_argument("--start", type=int, default=1, help="first seed to scan with --best-of")
    ap.add_argument("--mode", default="auto", choices=["auto", "record", "live", "mock", "replay"],
                    help="model for the agents: auto = Foundry if .env has credentials, else mock")
    ap.add_argument("--translate", default="de,pt,hi,ja,ar,sw", help="languages to pre-translate")
    ap.add_argument("--voice-langs", default="en,es,fr", help="commentary languages to voice")
    ap.add_argument("--no-translate", action="store_true")
    ap.add_argument("--no-voice", action="store_true")
    ap.add_argument("--no-judge", action="store_true", help="rules-only fact check (fewer model calls)")
    ap.add_argument("--skip-agents", action="store_true", help="reuse existing moments if there are any")
    ap.add_argument("--fresh", action="store_true", help="re-simulate even if the match file exists")
    ap.add_argument("--serve", action="store_true", help="start the app when done")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--cache", default="data/llm_cache.jsonl")
    ap.add_argument("--out", default="data")
    args = ap.parse_args()
    if args.seed is not None or args.match:
        args.best_of = None
    asyncio.run(produce(args))


if __name__ == "__main__":
    main()
