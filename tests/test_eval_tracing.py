import json
from pathlib import Path

from secondscreen.agents.foundry_eval import RulesEvaluator, build_dataset
from secondscreen import telemetry

DATA = Path(__file__).resolve().parents[1] / "data"


def test_tracing_off_without_connection_string(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    monkeypatch.setattr(telemetry, "_done", False)
    assert telemetry.setup_tracing() is False


def test_eval_dataset_rebuilds_facts_and_rules_pass():
    rows = build_dataset(DATA / "match_SS00076.jsonl", DATA / "match_SS00076.moments.jsonl")
    published = sum(1 for _ in (DATA / "match_SS00076.moments.jsonl").open(encoding="utf-8"))
    assert len(rows) == published
    ev = RulesEvaluator()
    for r in rows:
        assert r["context"] and r["response"]
        if r["source"] == "agents":
            assert ev(moment_json=r["moment_json"])["rules_grounded"] == 1, r["moment_id"]


def test_rules_evaluator_flags_invented_number():
    row = build_dataset(DATA / "match_SS00076.jsonl", DATA / "match_SS00076.moments.jsonl")[0]
    data = json.loads(row["moment_json"])
    data["draft"]["summary"] += " They have had 987 shots."
    assert RulesEvaluator()(moment_json=json.dumps(data))["rules_grounded"] == 0
