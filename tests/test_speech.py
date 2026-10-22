import xml.dom.minidom
from pathlib import Path

from secondscreen.cloud.speech import Speech, build_ssml, clips_for

DATA = Path(__file__).resolve().parents[1] / "data"


async def test_cache_then_mock_then_budget(tmp_path, monkeypatch):
    for k in ("AZURE_SPEECH_KEY", "AZURE_OPENAI_API_KEY", "SECONDSCREEN_SPEECH"):
        monkeypatch.delenv(k, raising=False)
    sp = Speech(cache_dir=tmp_path)
    assert await sp.speak("And it's in!", "en", "commentator", "peak") is None      # nothing configured or cached
    (tmp_path / f"{Speech.cache_key('And it is in!', 'en', 'commentator', 'peak')}.mp3").write_bytes(b"ID3cached")
    assert await sp.speak("And it is in!", "en", "commentator", "peak") == b"ID3cached"
    assert await sp.speak("And it is in!", "en", "pundit", "calm") is None           # other voice, other clip
    monkeypatch.setenv("SECONDSCREEN_SPEECH", "mock")
    sp = Speech(cache_dir=tmp_path, daily_chars=12)
    assert (await sp.speak("Quel arrêt !", "fr", "commentator", "peak"))[:4] == b"RIFF"
    assert await sp.speak("A much longer line over budget", "fr") is None


def test_ssml_is_valid_and_shaped():
    for voice in ("en-GB-RyanNeural", "en-us-Andrew:DragonHDLatestNeural"):
        for tone in ("build", "peak", "after", "calm"):
            ssml = build_ssml("Fallow & Quarry... rises... <b>", voice, tone)
            xml.dom.minidom.parseString(ssml)
            assert "<break" in ssml and "&amp;" in ssml
    assert "pitch" not in build_ssml("x", "en-us-Andrew:DragonHDLatestNeural", "peak")  # HD: style, not pitch
    assert "shouting" in build_ssml("x", "en-us-Andrew:DragonHDLatestNeural", "peak")


def test_commentary_clips_cover_every_part():
    line = {"lang": "en", "build": "a... b", "peak": "In!", "after": "Lead 1-0.", "pundit": "Calm words."}
    assert [c[2:] for c in clips_for({"en": line})] == [("commentator", "build"), ("commentator", "peak"),
                                                        ("commentator", "after"), ("pundit", "calm")]
