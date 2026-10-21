from secondscreen.cloud.speech import Speech, spoken_lines
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data"


async def test_cache_then_mock_then_budget(tmp_path, monkeypatch):
    for k in ("AZURE_SPEECH_KEY", "AZURE_OPENAI_API_KEY", "SECONDSCREEN_SPEECH"):
        monkeypatch.delenv(k, raising=False)
    sp = Speech(cache_dir=tmp_path)
    assert await sp.speak("Goal!", "en") is None                  # nothing configured, nothing cached
    (tmp_path / f"{Speech.cache_key('Goal!', 'en')}.mp3").write_bytes(b"ID3cached")
    assert await sp.speak("Goal!", "en") == b"ID3cached"          # replay from cache, no Azure
    monkeypatch.setenv("SECONDSCREEN_SPEECH", "mock")
    sp = Speech(cache_dir=tmp_path, daily_chars=12)
    assert (await sp.speak("Red card", "fr")).startswith(b"ID3")
    assert await sp.speak("A much longer line over budget", "fr") is None


def test_spoken_lines_cover_goals():
    lines = spoken_lines(DATA / "match_SS00076", "halcyon_fan")
    assert len(lines) >= 7 and all(text and lang == "en" for text, lang in lines)
