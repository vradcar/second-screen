"""python -m secondscreen.server [--host 0.0.0.0] [--port 8000]"""
from __future__ import annotations

import argparse

import uvicorn

from secondscreen.agents.llm import load_dotenv


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    load_dotenv()
    print(f"Second Screen running at http://{args.host}:{args.port}")
    uvicorn.run("secondscreen.server.app:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
