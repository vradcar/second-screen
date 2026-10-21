import json
from pathlib import Path

from secondscreen.highlights import pick

DATA = Path(__file__).resolve().parents[1] / "data"


def test_reel_has_every_goal_and_red_card_in_order():
    ms = [json.loads(l) for l in (DATA / "match_SS00076.moments.jsonl").open(encoding="utf-8")]
    clips = pick(ms)
    kinds = [c["kind"] for c in clips]
    assert kinds.count("goal") == sum(m["kind"] == "goal" for m in ms)
    assert "red_card" in kinds and len(clips) <= 10
    assert [c["elapsed"] for c in clips] == sorted(c["elapsed"] for c in clips)
    assert all(c["start"] < c["elapsed"] < c["end"] and c["headline"] for c in clips)
