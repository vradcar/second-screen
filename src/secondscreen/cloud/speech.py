"""Spoken commentary with Azure AI Speech: a two-voice commentary box.

A play-by-play commentator and a co-commentator, each a neural voice per language, read
the Commentator agent's fact-checked script. Each part of a call gets its own delivery:

    build   quicker, rising, with short pauses at "..."       commentator
    peak    the call: loud, fast, high (or an excited / shouting style where the voice has one)
    after   still up, landing it                               commentator
    calm    conversational                                     co-commentator

Audio is cached as MP3 under data/tts/, so a recorded demo replays without Azure.

Auth, in order:
  AZURE_SPEECH_KEY (or AZURE_OPENAI_API_KEY) + AZURE_SPEECH_REGION     key
  AZURE_SPEECH_RESOURCE_ID + managed identity / Azure login            Entra ID ("aad#<id>#<token>")

Voices are configurable: COMMENTATOR_VOICE_EN, PUNDIT_VOICE_EN (and _ES, _FR, ...), plus
COMMENTATOR_STYLE (e.g. "excited" or "shouting") for voices that support speaking styles.
HD voices (names containing ":DragonHD") read emotion from the text and take styles too.

    python -m secondscreen.cloud.speech --voices                 # which voices your region offers
    python -m secondscreen.cloud.speech data/match_SS00076       # prefill the commentary audio
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

# Default voice per language (also the fallback if a configured voice is rejected).
VOICES = {
    "en": "en-GB-RyanNeural", "es": "es-ES-AlvaroNeural", "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural", "it": "it-IT-DiegoNeural", "nl": "nl-NL-MaartenNeural", "pl": "pl-PL-MarekNeural",
    "tr": "tr-TR-AhmetNeural", "ar": "ar-SA-HamedNeural", "hi": "hi-IN-MadhurNeural", "bn": "bn-IN-BashkarNeural",
    "ja": "ja-JP-KeitaNeural", "ko": "ko-KR-InJoonNeural", "zh-Hans": "zh-CN-YunxiNeural", "id": "id-ID-ArdiNeural",
    "sw": "sw-KE-RafikiNeural",
}
PUNDITS = {"en": "en-GB-ThomasNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural",
           "de": "de-DE-KatjaNeural", "pt": "pt-BR-FranciscaNeural", "it": "it-IT-ElsaNeural"}
ROLES, TONES = ("commentator", "pundit"), ("build", "peak", "after", "calm")
MAX_CHARS = 300
FORMAT = "audio-24khz-96kbitrate-mono-mp3"
PROSODY = {   # tone -> (rate, pitch, volume); pitch is skipped on HD voices
    "build": ("+10%", "+5%", "loud"),
    "peak": ("+16%", "+16%", "x-loud"),
    "after": ("+8%", "+8%", "loud"),
    "calm": ("-2%", "+0%", "medium"),
}


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v if v and not v.startswith("<") else None


def voice_for(role: str, lang: str) -> str:
    suffix = lang.split("-")[0].upper()
    if role == "pundit":
        return _env(f"PUNDIT_VOICE_{suffix}") or PUNDITS.get(lang) or VOICES.get(lang, VOICES["en"])
    return _env(f"COMMENTATOR_VOICE_{suffix}") or VOICES.get(lang, VOICES["en"])


def locale_of(voice: str) -> str:
    return "-".join(voice.split(":")[0].split("-")[:2])


def build_ssml(text: str, voice: str, tone: str) -> str:
    """One commentary segment as SSML: '...' becomes a beat, the tone sets the delivery."""
    hd = ":DragonHD" in voice
    body = re.sub(r"\s*(?:\.\.\.|…)\s*", " <break time='260ms'/> ", escape(text)).strip()
    rate, pitch, volume = PROSODY[tone]
    attrs = f"rate='{rate}' volume='{volume}'" + ("" if hd else f" pitch='{pitch}'")
    inner = f"<prosody {attrs}>{body}</prosody>"
    style = _env("COMMENTATOR_STYLE") or ("excited" if hd else None)
    if style and tone in ("build", "peak", "after"):
        style = "shouting" if (hd and tone == "peak" and not _env("COMMENTATOR_STYLE")) else style
        inner = f"<mstts:express-as style='{style}' styledegree='2'>{inner}</mstts:express-as>"
    loc = locale_of(voice)
    return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='{loc}'><voice name='{voice}'>{inner}</voice></speak>")


class Speech:
    def __init__(self, cache_dir: Path | None = None, daily_chars: int | None = None):
        self.cache_dir = cache_dir or Path(os.environ.get("SECONDSCREEN_DATA", "data")) / "tts"
        self.key = _env("AZURE_SPEECH_KEY") or _env("AZURE_OPENAI_API_KEY")
        self.region = _env("AZURE_SPEECH_REGION") or "eastus"
        self.resource_id = _env("AZURE_SPEECH_RESOURCE_ID")
        self.mock = _env("SECONDSCREEN_SPEECH") == "mock"
        self.live = self.mock or bool(self.key or (self.resource_id and _env("AZURE_USE_IDENTITY")))
        self.budget = daily_chars if daily_chars is not None else int(os.environ.get("SPEECH_DAILY_CHARS", "60000"))
        self.used, self.day = 0, date.today()
        self._lock = threading.Lock()
        self._cred, self._token, self._token_exp = None, None, 0.0
        self._rejected: set[str] = set()

    def status(self) -> dict:
        cached = self.cache_dir.exists() and any(self.cache_dir.glob("*.mp3"))
        return {"available": self.live or cached, "live": self.live, "langs": list(VOICES)}

    @staticmethod
    def cache_key(text: str, lang: str, role: str = "commentator", tone: str = "after") -> str:
        voice = voice_for(role, lang if lang in VOICES else "en")
        return hashlib.sha1(f"{voice}|{tone}|{text}".encode()).hexdigest()[:20]

    async def speak(self, text: str, lang: str = "en", role: str = "commentator", tone: str = "after") -> bytes | None:
        """MP3 bytes, from the cache or Azure. None when unavailable or over budget."""
        text = " ".join(text.split())[:MAX_CHARS]
        lang = lang if lang in VOICES else "en"
        role = role if role in ROLES else "commentator"
        tone = tone if tone in TONES else ("calm" if role == "pundit" else "after")
        path = self.cache_dir / f"{self.cache_key(text, lang, role, tone)}.mp3"
        if path.exists():
            return path.read_bytes()
        if not self.live or not text or not self._spend(len(text)):
            return None
        audio = await asyncio.to_thread(self._call, text, lang, role, tone)
        if audio and not self.mock:
            try:
                self.cache_dir.mkdir(parents=True, exist_ok=True)
                path.write_bytes(audio)
            except OSError:
                pass
        return audio

    def _spend(self, n: int) -> bool:
        with self._lock:
            if date.today() != self.day:
                self.day, self.used = date.today(), 0
            if self.used + n > self.budget:
                return False
            self.used += n
            return True

    def _auth(self) -> dict:
        if self.key:
            return {"Ocp-Apim-Subscription-Key": self.key}
        if time.time() > self._token_exp - 120:
            from azure.identity import DefaultAzureCredential
            self._cred = self._cred or DefaultAzureCredential()
            tok = self._cred.get_token("https://cognitiveservices.azure.com/.default")
            self._token, self._token_exp = tok.token, tok.expires_on
        return {"Authorization": f"Bearer aad#{self.resource_id}#{self._token}"}

    def _post(self, ssml: str) -> bytes:
        req = urllib.request.Request(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(),
            headers={"Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": FORMAT,
                     "User-Agent": "second-screen"} | self._auth())
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def _call(self, text: str, lang: str, role: str, tone: str) -> bytes:
        if self.mock:      # silent WAV, about as long as the line would take to say
            return _silent_wav(max(0.6, 0.33 * len(text.split())))
        voice = voice_for(role, lang)
        if voice in self._rejected:
            voice = VOICES[lang]
        try:
            return self._post(build_ssml(text, voice, tone))
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # A voice or style this region doesn't have: plain default voice, prosody only.
            self._rejected.add(voice)
            os.environ.pop("COMMENTATOR_STYLE", None)
            return self._post(build_ssml(text, VOICES[lang], tone))

    def list_voices(self) -> list[dict]:
        req = urllib.request.Request(f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                                     headers=self._auth())
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)


def _silent_wav(seconds: float, rate: int = 8000) -> bytes:
    import struct
    n = int(seconds * rate)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
            + b"data" + struct.pack("<I", n) + b"\x80" * n)


# ------------------------------------------------------------------ prefill
def clips_for(commentary: dict, langs: list[str] | None = None) -> list[tuple[str, str, str, str]]:
    """(text, lang, role, tone) for every segment of a moment's commentary."""
    out = []
    for lang, line in commentary.items():
        if langs and lang not in langs:
            continue
        for part, role, tone in (("build", "commentator", "build"), ("peak", "commentator", "peak"),
                                 ("after", "commentator", "after"), ("pundit", "pundit", "calm")):
            if line.get(part):
                out.append((line[part], lang, role, tone))
    return out


async def prefill(prefix: Path, langs: list[str]) -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    sp = Speech(daily_chars=10**9)
    if not sp.live:
        raise SystemExit("Speech not configured: set AZURE_OPENAI_API_KEY (the Foundry resource key) and "
                         "AZURE_SPEECH_REGION if your resource is not in eastus.")
    path = prefix.with_suffix(".commentary.jsonl")
    if not path.exists():
        raise SystemExit(f"No commentary script at {path}. Run: python -m secondscreen.agents.commentary {prefix}")
    clips = {c for row in map(json.loads, path.open(encoding="utf-8")) for c in clips_for(row["commentary"], langs)}
    n = 0
    for text, lang, role, tone in sorted(clips):
        if await sp.speak(text, lang, role, tone):
            n += 1
    print(f"{n}/{len(clips)} clips in {sp.cache_dir} (voices: {voice_for('commentator', 'en')} + {voice_for('pundit', 'en')})")


def show_voices() -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    sp = Speech()
    vs = sp.list_voices()
    print(f"{len(vs)} voices in {sp.region}. Good fits for the commentary box:\n")
    for v in vs:
        name, loc = v["ShortName"], v["Locale"]
        if loc in ("en-GB", "en-US", "en-IE", "es-ES", "fr-FR") and (v.get("Gender") == "Male" or "DragonHD" in name):
            styles = ", ".join(v.get("StyleList", [])[:8])
            print(f"  {name:45s} {v.get('Gender', ''):7s} {styles}")
    print("\nSet COMMENTATOR_VOICE_EN / PUNDIT_VOICE_EN in .env, and COMMENTATOR_STYLE if the voice lists one.")


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.cloud.speech")
    ap.add_argument("match", nargs="?", help="data/match_<id> (no extension)")
    ap.add_argument("--langs", default="en,es,fr")
    ap.add_argument("--voices", action="store_true", help="list the voices your Speech region offers")
    args = ap.parse_args()
    if args.voices:
        show_voices()
    elif args.match:
        asyncio.run(prefill(Path(args.match.removesuffix(".jsonl")), [x for x in args.langs.split(",") if x]))
    else:
        ap.error("give a match, or --voices")


if __name__ == "__main__":
    main()
