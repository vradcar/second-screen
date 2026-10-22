import re
import xml.dom.minidom
from pathlib import Path

from secondscreen.cloud.speech import Speech, build_ssml, clips_for

DATA = Path(__file__).resolve().parents[1] / "data"


async def test_cache_then_mock_then_budget(tmp_path, monkeypatch):
    for k in ("AZURE_SPEECH_KEY", "AZURE_OPENAI_API_KEY", "SECONDSCREEN_SPEECH", "AZURE_TTS_DEPLOYMENT"):
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


def test_ssml_is_valid_and_natural():
    for voice in ("en-GB-RyanNeural", "en-us-Andrew:DragonHDLatestNeural"):
        for tone in ("call", "after", "calm"):
            ssml = build_ssml("Fallow & Quarry... rises... <b>", voice, tone)
            xml.dom.minidom.parseString(ssml)
            assert "<break" in ssml and "&amp;" in ssml
            assert not re.search(r"pitch='[+-]?\d+%'", ssml)   # Hz nudges only: % pitch sounds synthetic
    assert "excited" in build_ssml("x", "en-us-Andrew:DragonHDLatestNeural", "call")


def test_engine_choice_and_direction(monkeypatch):
    from secondscreen.cloud.speech import direction, engine, voice_for
    monkeypatch.delenv("AZURE_TTS_DEPLOYMENT", raising=False)
    assert engine() == "speech" and voice_for("commentator", "en") == "en-US-AndrewNeural"
    assert voice_for("pundit", "en") == "en-US-GuyNeural" and voice_for("commentator", "es") == "es-ES-AlvaroNeural"
    monkeypatch.setenv("AZURE_TTS_DEPLOYMENT", "gpt-4o-mini-tts")
    assert engine() == "openai" and voice_for("pundit", "en") == "ballad"
    assert "British" in direction("commentator", "call", "en") and "Spanish" in direction("commentator", "call", "es")


def test_commentary_clips_cover_every_part():
    line = {"lang": "en", "build": "a... b", "peak": "In!", "after": "Lead 1-0.", "pundit": "Calm words."}
    clips = clips_for({"en": line})
    assert clips[0] == ("a... b In!", "en", "commentator", "call")      # build-up and call in one take
    assert [c[2:] for c in clips[1:]] == [("commentator", "after"), ("pundit", "calm")]


def test_studypod_settings():
    call = build_ssml("And it's in!", "en-US-AndrewNeural", "call", "commentator")
    calm = build_ssml("Lovely finish.", "en-US-GuyNeural", "calm", "pundit")
    assert "rate='+12%' pitch='+3Hz'" in call and "rate='-4%' pitch='-2Hz'" in calm
