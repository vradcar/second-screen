import argparse
import json

from secondscreen.produce import produce


async def test_one_command_produces_any_match(tmp_path, monkeypatch):
    for k in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_AI_PROJECT_ENDPOINT", "AZURE_USE_IDENTITY"):
        monkeypatch.setenv(k, "")
    monkeypatch.setattr("secondscreen.agents.llm.load_dotenv", lambda *a, **k: None)
    args = argparse.Namespace(seed=4242, match=None, best_of=None, start=1, mode="auto", translate="de", voice_langs="en",
                              no_translate=True, no_voice=True, no_judge=False, skip_agents=False, fresh=False,
                              serve=False, port=8000, cache=str(tmp_path / "cache.jsonl"), out=str(tmp_path))
    await produce(args)
    moments = [json.loads(x) for x in (tmp_path / "match_SS04242.moments.jsonl").open(encoding="utf-8")]
    goals = [m for m in moments if m["kind"] == "goal"]
    assert goals and all({"en", "es", "fr"} <= set(m["commentary"]) for m in goals)
    assert all(m["commentary"]["en"]["peak"] for m in goals)
