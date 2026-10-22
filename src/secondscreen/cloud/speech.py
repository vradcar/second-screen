"""Spoken commentary: a two-voice commentary box.

A play-by-play commentator and a co-commentator read the Commentator agent's fact-checked
script. Two engines:

  gpt-4o-mini-tts (Azure OpenAI)   set AZURE_TTS_DEPLOYMENT. Steered with plain-English direction
                                   ("British TV football commentator... explode on the call"), so it
                                   sounds like a person calling a match. Preferred.
  Azure AI Speech neural voices    the fallback. Natural delivery, no pitch shifting.

Each moment is voiced as three takes: the build-up and the call in one breath, the landing
line, and the co-commentator. Audio is cached as MP3 under data/tts/, so a recorded demo
replays without Azure.

    python -m secondscreen.cloud.speech --samples                # voice every option, listen, pick
    python -m secondscreen.cloud.speech --voices                 # classic voices in your region
    python -m secondscreen.cloud.speech data/match_SS00076       # prefill a match's commentary audio

Settings: AZURE_TTS_DEPLOYMENT, TTS_VOICE_COMMENTATOR, TTS_VOICE_PUNDIT (gpt-4o-mini-tts);
COMMENTATOR_VOICE_EN, PUNDIT_VOICE_EN, COMMENTATOR_STYLE, AZURE_SPEECH_REGION (classic voices).
Keys: AZURE_OPENAI_API_KEY / AZURE_SPEECH_KEY, or the app's managed identity.
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

# Default classic voice per language (also the fallback if a configured voice is rejected).
VOICES = {
    "en": "en-GB-RyanNeural", "es": "es-ES-AlvaroNeural", "fr": "fr-FR-HenriNeural", "de": "de-DE-ConradNeural",
    "pt": "pt-BR-AntonioNeural", "it": "it-IT-DiegoNeural", "nl": "nl-NL-MaartenNeural", "pl": "pl-PL-MarekNeural",
    "tr": "tr-TR-AhmetNeural", "ar": "ar-SA-HamedNeural", "hi": "hi-IN-MadhurNeural", "bn": "bn-IN-BashkarNeural",
    "ja": "ja-JP-KeitaNeural", "ko": "ko-KR-InJoonNeural", "zh-Hans": "zh-CN-YunxiNeural", "id": "id-ID-ArdiNeural",
    "sw": "sw-KE-RafikiNeural",
}
# English defaults: the pairing from StudyPod's podcast, which sounded natural (energetic host +
# chill, deeper host), with the same gentle settings.
COMMENTATORS = {"en": "en-US-AndrewNeural"}
PUNDITS = {"en": "en-US-GuyNeural", "es": "es-ES-ElviraNeural", "fr": "fr-FR-DeniseNeural",
           "de": "de-DE-KatjaNeural", "pt": "pt-BR-FranciscaNeural", "it": "it-IT-ElsaNeural"}
# gpt-4o-mini-tts voices (one for each seat in the box); the accent and delivery come from the direction below.
OPENAI_VOICES = {"commentator": "ash", "pundit": "ballad"}
ROLES = ("commentator", "pundit")
TONES = ("call", "after", "calm", "pbp", "build", "peak")      # build/peak kept for older scripts
MAX_CHARS = 300
FORMAT = "audio-24khz-96kbitrate-mono-mp3"
LANG_NAMES = {"en": "English", "es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian"}

# Direction for gpt-4o-mini-tts: how a real commentary box sounds.
DIRECTION = {
    ("commentator", "call"): (
        "You are a play-by-play commentator on live English top-flight football on TV, with a British accent. "
        "Read this as live action happening in front of you. Start quick and engaged on the build-up, each "
        "fragment rising in urgency, short natural breaths at the pauses, and then explode on the final "
        "exclamation: a full-throated, joyful, drawn-out call with the crowd behind you. Genuine, human, "
        "spontaneous. Never flat, never robotic, never sing-song."),
    ("commentator", "after"): (
        "You are a British TV football commentator a second after a huge moment: still buzzing, slightly out "
        "of breath, voice raised but coming down, emphatic on the name and the score. Warm and natural."),
    ("commentator", "pbp"): (
        "You are a British TV football commentator talking through live play as the ball moves: names said "
        "crisply, engaged and lively but not shouting, the natural rhythm of running commentary."),
    ("pundit", "calm"): (
        "You are the co-commentator on English top-flight football on TV: a former professional player with a "
        "British accent. Relaxed, conversational and knowing, like talking to a friend at the match. Natural "
        "pace, a little smile in the voice, emphasise the one key point. Not a newsreader."),
}


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v if v and not v.startswith("<") else None


def engine() -> str:
    """'openai' (gpt-4o-mini-tts, steerable and far more human) when a deployment is configured,
    else 'speech' (Azure AI Speech neural voices)."""
    return "openai" if _env("AZURE_TTS_DEPLOYMENT") else "speech"


def direction(role: str, tone: str, lang: str) -> str:
    tone = {"build": "call", "peak": "call"}.get(tone, tone)
    text = DIRECTION.get((role, tone)) or DIRECTION[("pundit", "calm") if role == "pundit" else ("commentator", "after")]
    if lang != "en":
        name = LANG_NAMES.get(lang, lang)
        text += (f" Speak in {name}, as a native {name}-language football commentator would, with that "
                 f"country's commentary style and accent (ignore the British accent above).")
    return text


def voice_for(role: str, lang: str, eng: str | None = None) -> str:
    suffix = lang.split("-")[0].upper()
    if (eng or engine()) == "openai":
        return _env(f"TTS_VOICE_{role.upper()}") or OPENAI_VOICES[role]
    if role == "pundit":
        return _env(f"PUNDIT_VOICE_{suffix}") or PUNDITS.get(lang) or VOICES.get(lang, VOICES["en"])
    return _env(f"COMMENTATOR_VOICE_{suffix}") or COMMENTATORS.get(lang) or VOICES.get(lang, VOICES["en"])


def locale_of(voice: str) -> str:
    return "-".join(voice.split(":")[0].split("-")[:2])


# role -> (rate, pitch). Small nudges only: a few Hz of pitch, never percentages (that's what
# makes neural voices sound synthetic). Commentator values are StudyPod's energetic host.
PROSODY = {"commentator": ("+12%", "+3Hz"), "pundit": ("-4%", "-2Hz")}


def build_ssml(text: str, voice: str, tone: str, role: str | None = None) -> str:
    """Classic voices: natural delivery with a light per-seat nudge, a short beat at '...', and a
    speaking style where the voice has one."""
    role = role or ("pundit" if tone == "calm" else "commentator")
    hd = ":DragonHD" in voice
    body = re.sub(r"\s*(?:\.\.\.|…)\s*", " <break time='180ms'/> ", escape(text)).strip()
    rate, pitch = (_env(f"{role.upper()}_RATE") or PROSODY[role][0]), (_env(f"{role.upper()}_PITCH") or PROSODY[role][1])
    inner = f"<prosody rate='{rate}'" + ("" if hd else f" pitch='{pitch}'") + f">{body}</prosody>"
    style = _env("COMMENTATOR_STYLE") or ("excited" if hd else None)
    if style and role == "commentator":
        inner = f"<mstts:express-as style='{style}'>{inner}</mstts:express-as>"
    return (f"<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' "
            f"xmlns:mstts='https://www.w3.org/2001/mstts' xml:lang='{locale_of(voice)}'>"
            f"<voice name='{voice}'>{inner}</voice></speak>")


class Speech:
    def __init__(self, cache_dir: Path | None = None, daily_chars: int | None = None):
        self.cache_dir = cache_dir or Path(os.environ.get("SECONDSCREEN_DATA", "data")) / "tts"
        self.engine = engine()
        self.key = _env("AZURE_SPEECH_KEY") or _env("AZURE_OPENAI_API_KEY")
        self.region = _env("AZURE_SPEECH_REGION") or "eastus"
        self.resource_id = _env("AZURE_SPEECH_RESOURCE_ID")
        self.mock = _env("SECONDSCREEN_SPEECH") == "mock"
        if self.engine == "openai":
            self.live = self.mock or bool(_env("AZURE_TTS_ENDPOINT") or _env("AZURE_OPENAI_ENDPOINT"))
        else:
            self.live = self.mock or bool(self.key or (self.resource_id and _env("AZURE_USE_IDENTITY")))
        self.budget = daily_chars if daily_chars is not None else int(os.environ.get("SPEECH_DAILY_CHARS", "250000"))
        self.used, self.day = 0, date.today()
        self._lock = threading.Lock()
        self._cred, self._token, self._token_exp = None, None, 0.0
        self._rejected: set[str] = set()
        self._oai = None

    def status(self) -> dict:
        cached = self.cache_dir.exists() and any(self.cache_dir.glob("*.mp3"))
        return {"available": self.live or cached, "live": self.live, "engine": self.engine, "langs": list(VOICES)}

    @staticmethod
    def cache_key(text: str, lang: str, role: str = "commentator", tone: str = "after") -> str:
        eng = engine()
        voice = voice_for(role, lang if lang in VOICES else "en", eng)
        extra = direction(role, tone, lang) if eng == "openai" else ""
        return hashlib.sha1(f"{eng}|{voice}|{tone}|{extra}|{text}".encode()).hexdigest()[:20]

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

    def _token_value(self) -> str:
        if time.time() > self._token_exp - 120:
            from azure.identity import DefaultAzureCredential
            self._cred = self._cred or DefaultAzureCredential()
            tok = self._cred.get_token("https://cognitiveservices.azure.com/.default")
            self._token, self._token_exp = tok.token, tok.expires_on
        return self._token

    def _auth(self) -> dict:
        if self.key:
            return {"Ocp-Apim-Subscription-Key": self.key}
        return {"Authorization": f"Bearer aad#{self.resource_id}#{self._token_value()}"}

    def _post(self, ssml: str) -> bytes:
        req = urllib.request.Request(
            f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/v1", data=ssml.encode(),
            headers={"Content-Type": "application/ssml+xml", "X-Microsoft-OutputFormat": FORMAT,
                     "User-Agent": "second-screen"} | self._auth())
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()

    def _openai(self, text: str, lang: str, role: str, tone: str, voice: str | None = None) -> bytes:
        if self._oai is None:
            from openai import AzureOpenAI
            kw = {"azure_endpoint": _env("AZURE_TTS_ENDPOINT") or _env("AZURE_OPENAI_ENDPOINT"),
                  "api_version": _env("AZURE_TTS_API_VERSION") or "2025-03-01-preview"}
            key = _env("AZURE_TTS_API_KEY") or _env("AZURE_OPENAI_API_KEY")
            self._oai = AzureOpenAI(api_key=key, **kw) if key else AzureOpenAI(
                azure_ad_token_provider=self._token_value, **kw)
        r = self._oai.audio.speech.create(model=_env("AZURE_TTS_DEPLOYMENT"), voice=voice or voice_for(role, lang),
                                          input=text, instructions=direction(role, tone, lang), response_format="mp3")
        return r.read()

    def _call(self, text: str, lang: str, role: str, tone: str) -> bytes:
        if self.mock:      # silent WAV, about as long as the line would take to say
            return _silent_wav(max(0.6, 0.33 * len(text.split())))
        if self.engine == "openai":
            try:
                return self._openai(text, lang, role, tone)
            except Exception as e:  # noqa: BLE001
                if "DeploymentNotFound" not in str(e) and getattr(e, "status_code", None) != 404 or not self.key:
                    raise
                # The gpt-4o-mini-tts deployment isn't there: use Azure Speech voices from now on.
                import logging
                logging.getLogger(__name__).warning("AZURE_TTS_DEPLOYMENT not found; using Azure Speech voices")
                os.environ.pop("AZURE_TTS_DEPLOYMENT", None)
                self.engine = "speech"
        voice = voice_for(role, lang)
        if voice in self._rejected:
            voice = VOICES[lang]
        try:
            return self._post(build_ssml(text, voice, tone, role))
        except urllib.error.HTTPError as e:
            if e.code != 400:
                raise
            # A voice or style this region doesn't have: the default voice, no style.
            self._rejected.add(voice)
            os.environ.pop("COMMENTATOR_STYLE", None)
            return self._post(build_ssml(text, VOICES[lang], tone, role))

    def list_voices(self) -> list[dict]:
        req = urllib.request.Request(f"https://{self.region}.tts.speech.microsoft.com/cognitiveservices/voices/list",
                                     headers=self._auth())
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)


def explain_error(e: Exception) -> str:
    """A voice failure in plain words, with the fix."""
    eng = engine()
    body = ""
    if isinstance(e, urllib.error.HTTPError):
        try:
            body = e.read().decode(errors="replace")[:200]
        except Exception:  # noqa: BLE001
            pass
        code = e.code
    else:
        code = getattr(e, "status_code", None)
    msg = f"{type(e).__name__}{f' {code}' if code else ''}: {str(e)[:160]} {body}".strip()
    if eng == "openai":
        return (f"gpt-4o-mini-tts failed ({msg}). AZURE_TTS_DEPLOYMENT is set in .env but that model isn't "
                "deployed here: remove the line to use Azure Speech voices.")
    if code == 401:
        return (f"Azure Speech refused the key ({msg}). Set AZURE_SPEECH_REGION to your Foundry resource's region "
                f"(now '{_env('AZURE_SPEECH_REGION') or 'eastus'}'), or AZURE_SPEECH_KEY to its key.")
    if code == 400:
        return f"Azure Speech rejected the request ({msg}). A voice name in .env may not exist in your region."
    if code == 429:
        return f"Azure Speech rate limit ({msg}). Try again in a moment."
    return f"Voice failed: {msg}"


def doctor() -> None:
    """One test line through the configured voice, with what's set and what to fix."""
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    sp = Speech(daily_chars=10**9)
    print(f"engine:      {sp.engine}" + ("  (AZURE_TTS_DEPLOYMENT is set)" if sp.engine == "openai" else ""))
    print(f"key:         {'set' if sp.key else 'MISSING (AZURE_OPENAI_API_KEY or AZURE_SPEECH_KEY)'}")
    print(f"region:      {sp.region}")
    print(f"voices:      {voice_for('commentator', 'en')} (commentator), {voice_for('pundit', 'en')} (pundit)")
    try:
        audio = sp._call("And it's in! What a goal!", "en", "commentator", "call")
    except Exception as e:  # noqa: BLE001
        print("\nFAILED: " + explain_error(e))
        raise SystemExit(1)
    out = Path("data") / "tts_samples" / "voice_check.mp3"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(audio)
    print(f"\nOK: {len(audio):,} bytes of audio -> {out} (open it to listen)")


def _silent_wav(seconds: float, rate: int = 8000) -> bytes:
    import struct
    n = int(seconds * rate)
    return (b"RIFF" + struct.pack("<I", 36 + n) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate, 1, 8)
            + b"data" + struct.pack("<I", n) + b"\x80" * n)


# ------------------------------------------------------------------ prefill
def clips_for(commentary: dict, langs: list[str] | None = None) -> list[tuple[str, str, str, str]]:
    """(text, lang, role, tone) for a moment's commentary: the build-up and the call as one take
    (so it flows like one breath), the landing line, and the co-commentator."""
    out = []
    for lang, line in commentary.items():
        if langs and lang not in langs:
            continue
        call = " ".join(x for x in (line.get("build", ""), line.get("peak", "")) if x).strip()
        for text, role, tone in ((call, "commentator", "call"), (line.get("after", ""), "commentator", "after"),
                                 (line.get("pundit", ""), "pundit", "calm")):
            if text:
                out.append((text, lang, role, tone))
    return out


def commentary_scripts(prefix: Path) -> dict[str, dict]:
    """moment_id -> {lang: line}: from the moments themselves (written by the workflow), else from
    the batch file (agents.commentary) for runs recorded before the commentator existed."""
    out: dict[str, dict] = {}
    batch = prefix.with_suffix(".commentary.jsonl")
    if batch.exists():
        out |= {r["moment_id"]: r["commentary"] for r in map(json.loads, batch.open(encoding="utf-8"))}
    moments = prefix.with_suffix(".moments.jsonl")
    if moments.exists():
        out |= {m["moment_id"]: m["commentary"] for m in map(json.loads, moments.open(encoding="utf-8"))
                if m.get("commentary")}
    return out


def running_lines(prefix: Path, langs: list[str]) -> list[tuple[str, str, str, str]]:
    """(text, lang, role, tone) for the running play-by-play of a match (the spotter's lines)."""
    if not langs:
        return []
    from secondscreen.agents.spotter import Spotter
    sp, out = Spotter(langs), []
    for line in prefix.with_suffix(".jsonl").open(encoding="utf-8"):
        sp.feed(json.loads(line))
        for ln in sp.take_lines():
            tone = "calm" if ln["role"] == "pundit" else "pbp"
            out += [(ln["text"][lang], lang, ln["role"], tone) for lang in langs]
    return out


async def prefill(prefix: Path, langs: list[str], pbp_langs: list[str] | None = None) -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    sp = Speech(daily_chars=10**9)
    if not sp.live:
        raise SystemExit("Speech not configured: set AZURE_OPENAI_API_KEY (the Foundry resource key) and "
                         "AZURE_SPEECH_REGION if your resource is not in eastus.")
    scripts = commentary_scripts(prefix)
    if not scripts:
        raise SystemExit(f"No commentary for {prefix.name}. Run: python -m secondscreen.agents.commentary {prefix}")
    clips = {c for script in scripts.values() for c in clips_for(script, langs)}
    clips |= {c for c in running_lines(prefix, pbp_langs if pbp_langs is not None else langs[:1])}
    n = 0
    for text, lang, role, tone in sorted(clips):
        if await sp.speak(text, lang, role, tone):
            n += 1
    print(f"{n}/{len(clips)} clips in {sp.cache_dir} ({sp.engine}: {voice_for('commentator', 'en')} + "
          f"{voice_for('pundit', 'en')})")


SAMPLE = {"call": "Fallow whips it in... Quarry rises... And he's headed it in!",
          "after": "Isak Quarry! Level at 1-1, and the ten men are back in it!",
          "calm": "Only 0.11 xG on that, so there really wasn't much on. But that's a finish of real quality."}


def samples(out: Path) -> None:
    """Voice the same goal call and pundit line with every option, so you can listen and choose."""
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    out.mkdir(parents=True, exist_ok=True)
    made, failed = [], []

    def save(name: str, fn) -> None:
        try:
            (out / f"{name}.mp3").write_bytes(fn())
            made.append(name)
        except Exception as e:  # noqa: BLE001 - report and carry on with the next option
            failed.append(f"{name}: {type(e).__name__}: {str(e)[:160]}")

    sp = Speech(daily_chars=10**9)
    if _env("AZURE_TTS_DEPLOYMENT"):
        for v in ("ash", "verse", "ballad", "onyx", "echo", "cedar"):
            save(f"gpt4o-tts_commentator_{v}", lambda v=v: sp._openai(f"{SAMPLE['call']} {SAMPLE['after']}", "en",
                                                                         "commentator", "call", v))
        for v in ("ballad", "sage", "ash", "cedar"):
            save(f"gpt4o-tts_pundit_{v}", lambda v=v: sp._openai(SAMPLE["calm"], "en", "pundit", "calm", v))
    else:
        failed.append("gpt-4o-mini-tts: skipped, AZURE_TTS_DEPLOYMENT isn't set (deploy gpt-4o-mini-tts in Foundry)")
    if sp.key:
        voices = ["en-US-AndrewNeural", "en-US-GuyNeural", "en-GB-RyanNeural", "en-GB-ThomasNeural"]
        try:
            listed = sp.list_voices()
            pick = lambda f, n: [v["ShortName"] for v in listed if f(v["ShortName"]) and v.get("Gender") == "Male"  # noqa: E731
                                 and v["Locale"] in ("en-GB", "en-US")][:n]
            voices += pick(lambda n: "Multilingual" in n, 4) + pick(lambda n: "DragonHD" in n, 4)
        except Exception as e:  # noqa: BLE001
            failed.append(f"voice list: {e}")
        for v in voices:
            tag = v.replace(":", "_")
            save(f"speech_call_{tag}", lambda v=v: sp._post(build_ssml(f"{SAMPLE['call']} {SAMPLE['after']}", v, "call",
                                                                       "commentator")))
            save(f"speech_pundit_{tag}", lambda v=v: sp._post(build_ssml(SAMPLE["calm"], v, "calm", "pundit")))
    print(f"{len(made)} samples in {out}:")
    for m in made:
        print("  " + m)
    for f in failed:
        print("  not made: " + f)
    print("\nPick the ones you like, then in .env:\n"
          "  gpt-4o-mini-tts: AZURE_TTS_DEPLOYMENT=<name>, TTS_VOICE_COMMENTATOR=<voice>, TTS_VOICE_PUNDIT=<voice>\n"
          "  classic voices:  COMMENTATOR_VOICE_EN=<voice>, PUNDIT_VOICE_EN=<voice>")


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
    ap.add_argument("--pbp-langs", default="en", help="languages to voice the running play-by-play in ('' for none)")
    ap.add_argument("--voices", action="store_true", help="list the voices your Speech region offers")
    ap.add_argument("--samples", action="store_true", help="voice a sample call with every option, to listen and pick")
    ap.add_argument("--check", action="store_true", help="test the voice setup and say what to fix")
    args = ap.parse_args()
    if args.check:
        doctor()
    elif args.samples:
        samples(Path("data") / "tts_samples")
    elif args.voices:
        show_voices()
    elif args.match:
        asyncio.run(prefill(Path(args.match.removesuffix(".jsonl")), [x for x in args.langs.split(",") if x],
                            [x for x in args.pbp_langs.split(",") if x]))
    else:
        ap.error("give a match, --samples or --voices")


if __name__ == "__main__":
    main()
