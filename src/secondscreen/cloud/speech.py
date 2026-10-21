"""Spoken commentary with Azure AI Speech (neural text to speech).

The TV can read out the fact-checked strap for each big moment, in the persona's
language (or whichever language the viewer picked). Audio comes from the same
Foundry (AI Services) resource and is cached as MP3 under data/tts/, so a recorded
demo replays without calling Azure.

Auth, in order:
  AZURE_SPEECH_KEY (or AZURE_OPENAI_API_KEY) + AZURE_SPEECH_REGION     key
  AZURE_SPEECH_RESOURCE_ID + managed identity / Azure login            Entra ID ("aad#<id>#<token>")

Prefill the cache from a laptop:
    python -m secondscreen.cloud.speech data/match_SS00076 --persona halcyon_fan
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import threading
import time
import urllib.request
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape

VOICES = {
    "en": "en-GB-RyanNeural", "es": "es-ES-AlvaroNeural", "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural", "it": "it-IT-DiegoNeural", "nl": "nl-NL-MaartenNeural", "pl": "pl-PL-MarekNeural",
    "tr": "tr-TR-AhmetNeural", "ar": "ar-SA-HamedNeural", "hi": "hi-IN-MadhurNeural", "bn": "bn-IN-BashkarNeural",
    "ja": "ja-JP-KeitaNeural", "ko": "ko-KR-InJoonNeural", "zh-Hans": "zh-CN-YunxiNeural", "id": "id-ID-ArdiNeural",
    "sw": "sw-KE-RafikiNeural",
}
LOCALE = {k: "-".join(v.split("-")[:2]) for k, v in VOICES.items()}
MAX_CHARS = 300
FORMAT = "audio-24khz-48kbitrate-mono-mp3"


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v if v and not v.startswith("<") else None


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

    def status(self) -> dict:
        cached = self.cache_dir.exists() and any(self.cache_dir.glob("*.mp3"))
        return {"available": self.live or cached, "live": self.live, "langs": list(VOICES)}

    @staticmethod
    def cache_key(text: str, lang: str) -> str:
        return hashlib.sha1(f"{VOICES.get(lang, VOICES['en'])}|{text}".encode()).hexdigest()[:20]

    async def speak(self, text: str, lang: str = "en") -> bytes | None:
        """MP3 bytes, from the cache or Azure. None when unavailable or over budget."""
        text = " ".join(text.split())[:MAX_CHARS]
        lang = lang if lang in VOICES else "en"
        path = self.cache_dir / f"{self.cache_key(text, lang)}.mp3"
        if path.exists():
            return path.read_bytes()
        if not self.live or not text or not self._spend(len(text)):
            return None
        audio = await asyncio.to_thread(self._call, text, lang)
        if not self.mock:
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

    def _call(self, text: str, lang: str) -> bytes:
        if self.mock:
            return b"ID3" + text.encode()[:32]
        loc = LOCALE[lang]
        ssml = (f"<speak version='1.0' xml:lang='{loc}'><voice name='{VOICES[lang]}'>"
                f"<prosody rate='+6%'>{escape(text)}</prosody></voice></speak>")
        req = urllib.request.Request(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(),
            headers={"Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": FORMAT,
                     "User-Agent": "second-screen"} | self._auth())
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()


# ------------------------------------------------------------------ prefill
SPOKEN = {"goal", "red_card", "penalty_awarded", "big_save", "big_chance_missed", "late_surge", "hot_streak",
          "fatigue_fade", "pressing_spell"}


def spoken_lines(prefix: Path, persona: str) -> list[tuple[str, str]]:
    """(text, lang) for every moment the TV would read out, for one persona."""
    out = []
    for m in map(json.loads, prefix.with_suffix(".moments.jsonl").open(encoding="utf-8")):
        if m["kind"] in SPOKEN:
            r = next((r for r in m["renderings"] if r["persona_id"] == persona), m["renderings"][0])
            out.append((r["lower_third"], r["lang"]))
    return out


async def prefill(prefix: Path, personas: list[str], langs: list[str]) -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    sp = Speech(daily_chars=10**9)
    if not sp.live:
        raise SystemExit("Speech not configured: set AZURE_OPENAI_API_KEY (the Foundry resource key) and "
                         "AZURE_SPEECH_REGION if your resource is not in eastus.")
    lines = {ln for p in personas for ln in spoken_lines(prefix, p)}
    if langs:   # also voice the translated straps, from the Translator cache
        from secondscreen.cloud.translate import Translator
        tr = Translator()
        for text, src in list(lines):
            for to in langs:
                res = (await tr.translate([text], to, src))[0]
                if res["ok"]:
                    lines.add((res["text"], to))
    n = 0
    for text, lang in sorted(lines):
        if await sp.speak(text, lang):
            n += 1
    print(f"{n}/{len(lines)} clips in {sp.cache_dir}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.cloud.speech")
    ap.add_argument("match", help="data/match_<id> (no extension)")
    ap.add_argument("--persona", default="halcyon_fan,studio_analyst,redmarsh_fan_es,lazaro_cam_fr")
    ap.add_argument("--langs", default="", help="also voice translations, e.g. de,pt,hi (uses the Translator cache)")
    args = ap.parse_args()
    asyncio.run(prefill(Path(args.match.removesuffix(".jsonl")), args.persona.split(","),
                        [x for x in args.langs.split(",") if x]))


if __name__ == "__main__":
    main()
