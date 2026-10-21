import pytest

from secondscreen.cloud.translate import Translator, numbers_kept


def test_numbers_guard_is_script_and_decimal_tolerant():
    assert numbers_kept("xG 0.42 after 12 minutes", "xG 0,42 nach 12 Minuten")
    assert numbers_kept("3 shots", "३ शॉट")
    assert numbers_kept("2-1 up", "٢-١")
    assert not numbers_kept("3 shots", "4 Schüsse")
    assert not numbers_kept("1.76 times", "1.67 Mal")


def _tr(tmp_path, monkeypatch, **kw):
    monkeypatch.setenv("SECONDSCREEN_TRANSLATOR", "mock")
    return Translator(cache_file=tmp_path / "t.jsonl", **kw)


async def test_translate_mock_and_rejects_changed_numbers(tmp_path, monkeypatch):
    tr = _tr(tmp_path, monkeypatch)
    out = await tr.translate(["9 presses in 6 minutes", "Hola"], "de", "en")
    assert out[0] == {"text": "[de] 9 presses in 6 minutes", "ok": True}
    tr.cache[("en", "de", "4 goals")] = "5 Tore"            # a bad translation in the cache
    bad = (await tr.translate(["4 goals"], "de", "en"))[0]
    assert bad["ok"] is False and bad["text"] == "4 goals"   # the viewer sees the original


async def test_budget_and_unknown_language(tmp_path, monkeypatch):
    tr = _tr(tmp_path, monkeypatch, daily_chars=10)
    out = await tr.translate(["a long sentence over budget"], "de", "en")
    assert out[0]["ok"] is False and "budget" in out[0]["why"]
    with pytest.raises(ValueError):
        await tr.translate(["x"], "xx")


def test_cache_replays_without_azure(tmp_path, monkeypatch):
    for k in ("SECONDSCREEN_TRANSLATOR", "AZURE_OPENAI_ENDPOINT", "AZURE_TRANSLATOR_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)
    f = tmp_path / "t.jsonl"
    f.write_text('{"from": "en", "to": "ja", "text": "Goal", "out": "ゴール"}\n', encoding="utf-8")
    tr = Translator(cache_file=f)
    assert not tr.live and tr.status()["langs"] == [{"code": "ja", "name": "日本語", "rtl": False}]
