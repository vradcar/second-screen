"""Run the stats engine over a match file.

    python -m secondscreen.stats data/match_SS00076.jsonl          # print key signals
    python -m secondscreen.stats data/match_SS00076.jsonl --out data   # also write signals + snapshot
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from secondscreen.stats.engine import StatsEngine


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> None:
    _utf8_console()
    ap = argparse.ArgumentParser(prog="secondscreen.stats")
    ap.add_argument("path")
    ap.add_argument("--out", help="directory for <match>.signals.jsonl and <match>.snapshot.json")
    ap.add_argument("--min-importance", type=float, default=0.4)
    args = ap.parse_args()

    eng = StatsEngine()
    for line in Path(args.path).open(encoding="utf-8"):
        for sig in eng.ingest(json.loads(line)):
            if sig.importance >= args.min_importance:
                facts = {k: v for k, v in sig.facts.items() if not isinstance(v, dict)}
                print(f"{sig.clock:>7}  {sig.kind:<18} {sig.status:<7} {sig.team_id or '':<4} "
                      f"{json.dumps(facts)[:110]}")
    if args.out:
        out = Path(args.out)
        out.mkdir(parents=True, exist_ok=True)
        with (out / f"match_{eng.match_id}.signals.jsonl").open("w", encoding="utf-8") as f:
            for sig in eng.signals:
                f.write(json.dumps(sig.to_dict(), separators=(",", ":")) + "\n")
        (out / f"match_{eng.match_id}.snapshot.json").write_text(json.dumps(eng.snapshot(), indent=1), encoding="utf-8")
        print(f"\n{len(eng.signals)} signals -> {out}")


if __name__ == "__main__":
    main()
