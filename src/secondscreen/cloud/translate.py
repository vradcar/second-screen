"""Azure AI Translator for any-language second screens.

The persona agents write in English, Spanish and French. Translator takes any
published card into dozens more languages, on the same Foundry (AI Services)
resource, with the same guarantee as the rest of the pipeline: a translation is
only shown if every number in it matches the fact-checked original. Otherwise the
viewer sees the original text.

Auth, in order:
  AZURE_TRANSLATOR_KEY (or AZURE_OPENAI_API_KEY) + AZURE_TRANSLATOR_REGION     key
  AZURE_USE_IDENTITY / an Azure login                                          Entra ID
Endpoint: AZURE_TRANSLATOR_ENDPOINT, else derived from AZURE_OPENAI_ENDPOINT
(https://<resource>.cognitiveservices.azure.com).

Translations are cached in data/translations.jsonl so a recorded demo replays
without calling Azure. Prefill it from a laptop with:
    python -m secondscreen.cloud.translate data/match_SS00076 --to de,pt,hi,ja,ar,sw
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import threading
import time
import unicodedata
import urllib.request
from collections import Counter
from datetime import date
from pathlib import Path

LANGS = {
    "en": "English", "es": "Español", "fr": "Français", "de": "Deutsch", "pt": "Português", "it": "Italiano",
    "nl": "Nederlands", "pl": "Polski", "tr": "Türkçe", "ar": "العربية", "hi": "हिन्दी", "bn": "বাংলা",
    "ja": "日本語", "ko": "한국어", "zh-Hans": "中文", "id": "Bahasa Indonesia", "sw": "Kiswahili", "yo": "Yorùbá",
}
RTL = {"ar", "he", "fa", "ur"}
MAX_ITEMS, MAX_CHARS = 40, 600
CACHE_FILE = Path(os.environ.get("SECONDSCREEN_DATA", "data")) / "translations.jsonl"
# The phone's own English labels (web/src/personas.ts), translated alongside the cards.
UI_EN = ["Goal", "Red card", "Penalty", "Big save", "Big chance", "Pressing", "Momentum", "Game state", "On fire",
         "Fatigue", "Late surge", "Top speed", "Shot speed", "Booking", "Substitution", "Distance", "Pass of the game",
         "Fact-checked", "Revised after fact-check", "Safe template (agent draft rejected)",
         "Moments appear here as the match unfolds."]
NUM = re.compile(r"\d+(?:[.,]\d+)?")


def _env(name: str) -> str | None:
    v = (os.environ.get(name) or "").strip()
    return v if v and not v.startswith("<") else None


def numbers(text: str) -> Counter:
    """Numbers in a string, script-independent (Devanagari or Arabic-Indic digits count) and
    decimal-comma tolerant, so '0,42' in German matches '0.42' in English."""
    norm = "".join(str(unicodedata.digit(ch)) if ch.isdigit() else ch for ch in text)
    return Counter(n.replace(",", ".") for n in NUM.findall(norm))


def numbers_kept(source: str, translated: str) -> bool:
    return numbers(source) == numbers(translated)


class Translator:
    def __init__(self, cache_file: Path | None = CACHE_FILE, daily_chars: int | None = None):
        self.endpoint = _env("AZURE_TRANSLATOR_ENDPOINT") or _derive_endpoint(_env("AZURE_OPENAI_ENDPOINT"))
        self.key = _env("AZURE_TRANSLATOR_KEY") or _env("AZURE_OPENAI_API_KEY")
        self.region = _env("AZURE_TRANSLATOR_REGION") or "eastus"
        self.mock = _env("SECONDSCREEN_TRANSLATOR") == "mock"
        self.live = self.mock or bool(self.endpoint and (self.key or _env("AZURE_USE_IDENTITY") or _env("AZURE_TRANSLATOR_IDENTITY")))
        self.budget = daily_chars if daily_chars is not None else int(os.environ.get("TRANSLATE_DAILY_CHARS", "300000"))
        self.used, self.day = 0, date.today()
        self.cache: dict[tuple[str, str, str], str] = {}
        self.cache_file = cache_file
        self._lock = threading.Lock()
        self._cred = self._token = None
        self._token_exp = 0.0
        if cache_file and cache_file.exists():
            for line in cache_file.open(encoding="utf-8"):
                try:
                    r = json.loads(line)
                    self.cache[(r["from"], r["to"], r["text"])] = r["out"]
                except (ValueError, KeyError):
                    continue

    # ------------------------------------------------------------------ info
    def languages(self) -> list[str]:
        if self.live:
            return list(LANGS)
        cached = {to for _, to, _ in self.cache}
        return [c for c in LANGS if c in cached]

    def status(self) -> dict:
        langs = self.languages()
        return {"available": bool(langs), "live": self.live, "langs": [{"code": c, "name": LANGS.get(c, c),
                                                                          "rtl": c in RTL} for c in langs]}

    # ------------------------------------------------------------- translate
    async def translate(self, texts: list[str], to: str, src: str | None = None) -> list[dict]:
        """[{text, ok, why?}] in input order. ok=False means the original is returned."""
        if to not in LANGS:
            raise ValueError(f"unsupported language {to}")
        texts = [t[:MAX_CHARS] for t in texts[:MAX_ITEMS]]
        src = src if src in LANGS else None
        out: list[dict | None] = [None] * len(texts)
        todo: list[int] = []
        for i, t in enumerate(texts):
            if not t.strip() or src == to:
                out[i] = {"text": t, "ok": True}
            elif (hit := self.cache.get((src or "", to, t))) is not None:
                out[i] = self._guard(t, hit)
            else:
                todo.append(i)
        if todo:
            if not self.live:
                for i in todo:
                    out[i] = {"text": texts[i], "ok": False, "why": "not translated"}
            elif not self._spend(sum(len(texts[i]) for i in todo)):
                for i in todo:
                    out[i] = {"text": texts[i], "ok": False, "why": "daily translation budget used"}
            else:
                try:
                    got = await asyncio.to_thread(self._call, [texts[i] for i in todo], to, src)
                except Exception as e:  # noqa: BLE001 - translation is best-effort, the original still shows
                    for i in todo:
                        out[i] = {"text": texts[i], "ok": False, "why": f"translator error: {type(e).__name__}"}
                else:
                    for i, t in zip(todo, got):
                        self._remember(src or "", to, texts[i], t)
                        out[i] = self._guard(texts[i], t)
        return out  # type: ignore[return-value]

    def _guard(self, source: str, translated: str) -> dict:
        if numbers_kept(source, translated):
            return {"text": translated, "ok": True}
        return {"text": source, "ok": False, "why": "numbers changed in translation"}

    def _spend(self, n: int) -> bool:
        with self._lock:
            if date.today() != self.day:
                self.day, self.used = date.today(), 0
            if self.used + n > self.budget:
                return False
            self.used += n
            return True

    def _remember(self, src: str, to: str, text: str, out: str) -> None:
        with self._lock:
            self.cache[(src, to, text)] = out
            if self.cache_file and not self.mock:
                try:
                    with self.cache_file.open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"from": src, "to": to, "text": text, "out": out}, ensure_ascii=False) + "\n")
                except OSError:
                    pass   # read-only image: keep the in-memory cache

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self.key:
            h |= {"Ocp-Apim-Subscription-Key": self.key, "Ocp-Apim-Subscription-Region": self.region}
            return h
        if time.time() > self._token_exp - 120:
            from azure.identity import DefaultAzureCredential
            self._cred = self._cred or DefaultAzureCredential()
            tok = self._cred.get_token("https://cognitiveservices.azure.com/.default")
            self._token, self._token_exp = tok.token, tok.expires_on
        return h | {"Authorization": f"Bearer {self._token}"}

    def _call(self, texts: list[str], to: str, src: str | None) -> list[str]:
        if self.mock:
            return [f"[{to}] {t}" for t in texts]
        q = f"api-version=3.0&to={to}" + (f"&from={src}" if src else "")
        req = urllib.request.Request(f"{self.endpoint.rstrip('/')}/translator/text/v3.0/translate?{q}",
                                     data=json.dumps([{"Text": t} for t in texts]).encode(), headers=self._headers())
        with urllib.request.urlopen(req, timeout=15) as r:
            return [item["translations"][0]["text"] for item in json.load(r)]


def _derive_endpoint(openai_endpoint: str | None) -> str | None:
    if not openai_endpoint:
        return None
    m = re.match(r"https://([^.]+)\.(openai\.azure\.com|services\.ai\.azure\.com|cognitiveservices\.azure\.com)", openai_endpoint)
    return f"https://{m.group(1)}.cognitiveservices.azure.com" if m else None


# --------------------------------------------------------------------- prefill
def card_texts(prefix: Path) -> dict[str, set[str]]:
    """Everything a phone shows for a recorded match, grouped by source language."""
    by_lang: dict[str, set[str]] = {"en": set(UI_EN)}
    for m in map(json.loads, prefix.with_suffix(".moments.jsonl").open(encoding="utf-8")):
        for r in m["renderings"]:
            s = by_lang.setdefault(r["lang"], set())
            s |= {r["lower_third"], r["body"]} | {c["label"] for c in r.get("stat_chips", [])}
    cues = prefix.with_suffix(".cues.jsonl")
    if cues.exists():
        for c in map(json.loads, cues.open(encoding="utf-8")):
            if not c.get("moment_id"):
                by_lang.setdefault(c.get("lang", "en"), set()).update(s["label"] for s in c.get("stats", []))
    return by_lang


async def prefill(prefix: Path, langs: list[str]) -> None:
    from secondscreen.agents.llm import load_dotenv
    load_dotenv()
    tr = Translator()
    if not tr.live:
        raise SystemExit("Translator not configured: set AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_API_KEY "
                         "(plus AZURE_TRANSLATOR_REGION if your resource is not in eastus).")
    tr.budget = 10**9
    groups = card_texts(prefix)
    for to in langs:
        ok = bad = 0
        for src, texts in groups.items():
            items = sorted(texts)
            for i in range(0, len(items), MAX_ITEMS):
                for r in await tr.translate(items[i:i + MAX_ITEMS], to, src):
                    ok += r["ok"]
                    bad += not r["ok"]
        print(f"{to}: {ok} translated, {bad} kept original")
    print(f"cache: {tr.cache_file}")


def main() -> None:
    ap = argparse.ArgumentParser(prog="secondscreen.cloud.translate")
    ap.add_argument("match", help="data/match_<id> (no extension)")
    ap.add_argument("--to", default="de,pt,hi,ja,ar,sw", help="comma-separated language codes")
    args = ap.parse_args()
    prefix = Path(args.match.removesuffix(".jsonl"))
    asyncio.run(prefill(prefix, [x.strip() for x in args.to.split(",") if x.strip()]))


if __name__ == "__main__":
    main()
