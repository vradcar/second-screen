"""Evaluate published moments with Microsoft Foundry evaluators and log the run to
the Foundry project.

For every moment the agents published, the evaluators see:
    context   the stats-engine facts available when it was written (rebuilt from the events)
    response  what went on air (headline, summary, why it matters)
and score it with Foundry's GroundednessEvaluator, RelevanceEvaluator and
CoherenceEvaluator, plus our own deterministic grounding rules as a code evaluator.

    python -m secondscreen.agents.foundry_eval data/match_SS00076.jsonl            # local results
    python -m secondscreen.agents.foundry_eval data/match_SS00076.jsonl --upload   # + Foundry portal

Needs AZURE_OPENAI_ENDPOINT (+ AZURE_OPENAI_API_KEY, or an Azure login) for the judge
model, and AZURE_AI_PROJECT_ENDPOINT plus an Azure login to upload.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from secondscreen.agents.context import build_context
from secondscreen.agents.factcheck import check_draft
from secondscreen.agents.llm import _env, load_dotenv
from secondscreen.agents.schemas import MomentDraft
from secondscreen.agents.templates import is_narrative
from secondscreen.stats.engine import StatsEngine


def build_dataset(events_path: Path, moments_path: Path) -> list[dict]:
    """One row per published moment, with the facts the agents saw rebuilt from the event feed."""
    moments = {m["signal_id"]: m for m in map(json.loads, moments_path.open(encoding="utf-8"))}
    eng, story, flagged, rows = StatsEngine(), [], [], []
    for line in events_path.open(encoding="utf-8"):
        for sig in eng.ingest(json.loads(line)):
            s = sig.to_dict()
            if not is_narrative(s, flagged):
                continue
            flagged.append({"kind": s["kind"], "elapsed": s["elapsed"]})
            m = moments.get(s["signal_id"])
            if not m:
                continue
            ctx = build_context(s, eng, story)
            d = m["draft"]
            rows.append({
                "moment_id": m["moment_id"], "kind": m["kind"], "clock": m["clock"], "source": m["source"],
                "attempts": m["attempts"],
                "query": f"Explain why this {m['kind'].replace('_', ' ')} at {m['clock']} matters for the match.",
                "context": "\n".join(f"{k} = {v}" for k, v in ctx["facts"].items()),
                "response": f"{d['headline']}. {d['summary']} {d['why_it_matters']}",
                "moment_json": json.dumps({"draft": d, "facts": ctx["facts"], "roster": ctx["roster"],
                                           "story_so_far": ctx["story_so_far"]}),
            })
            story.append(m)
    return rows


class RulesEvaluator:
    """Our deterministic grounding rules as a Foundry code evaluator: 1 if every number,
    name and cited fact key in the moment traces to the stats engine, else 0."""

    def __call__(self, *, moment_json: str):
        data = json.loads(moment_json)
        issues = check_draft(MomentDraft.model_validate(data["draft"]),
                             {"facts": data["facts"], "roster": data["roster"],
                              "story_so_far": data["story_so_far"]})
        return {"rules_grounded": 0 if issues else 1, "rules_issues": "; ".join(issues)[:500]}


def model_config() -> dict:
    cfg = {"azure_endpoint": _env("AZURE_OPENAI_ENDPOINT"),
           "azure_deployment": _env("AZURE_OPENAI_DEPLOYMENT") or "gpt-4.1-mini",
           "api_version": _env("AZURE_OPENAI_API_VERSION") or "2024-10-21"}
    if _env("AZURE_OPENAI_API_KEY"):
        cfg["api_key"] = _env("AZURE_OPENAI_API_KEY")
    return cfg


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.agents.foundry_eval")
    ap.add_argument("events", help="data/match_<id>.jsonl")
    ap.add_argument("--moments", help="defaults to data/match_<id>.moments.jsonl")
    ap.add_argument("--out", default="data/eval")
    ap.add_argument("--upload", action="store_true", help="log the run to the Foundry project")
    ap.add_argument("--rules-only", action="store_true", help="skip the model-based evaluators")
    args = ap.parse_args()
    load_dotenv()

    events = Path(args.events)
    moments = Path(args.moments) if args.moments else events.with_name(events.stem + ".moments.jsonl")
    rows = build_dataset(events, moments)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    data = out / f"{events.stem}.eval_input.jsonl"
    with data.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(rows)} moments -> {data}")

    from azure.ai.evaluation import CoherenceEvaluator, GroundednessEvaluator, RelevanceEvaluator, evaluate
    evaluators: dict = {"rules": RulesEvaluator()}
    if not args.rules_only:
        cfg = model_config()
        if not cfg["azure_endpoint"]:
            raise SystemExit("Set AZURE_OPENAI_ENDPOINT (and AZURE_OPENAI_API_KEY) for the judge model, or use --rules-only.")
        evaluators |= {"groundedness": GroundednessEvaluator(cfg), "relevance": RelevanceEvaluator(cfg),
                       "coherence": CoherenceEvaluator(cfg)}
    project = _env("AZURE_AI_PROJECT_ENDPOINT") if args.upload else None
    if args.upload and not project:
        raise SystemExit("Set AZURE_AI_PROJECT_ENDPOINT to upload to Foundry.")
    result = evaluate(
        data=str(data), evaluators=evaluators, evaluation_name=f"second-screen {events.stem}",
        azure_ai_project=project, output_path=str(out / f"{events.stem}.eval_result.json"),
        evaluator_config={
            "rules": {"column_mapping": {"moment_json": "${data.moment_json}"}},
            "groundedness": {"column_mapping": {"query": "${data.query}", "context": "${data.context}", "response": "${data.response}"}},
            "relevance": {"column_mapping": {"query": "${data.query}", "response": "${data.response}"}},
            "coherence": {"column_mapping": {"query": "${data.query}", "response": "${data.response}"}},
        },
        tags={"match": events.stem, "pipeline": "analyst-factchecker-persona"},
    )
    metrics = result.get("metrics", {})
    print(json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in metrics.items()}, indent=1))
    if result.get("studio_url"):
        print("Foundry:", result["studio_url"])


if __name__ == "__main__":
    os.environ.setdefault("PF_DISABLE_TRACING", "true")
    main()
