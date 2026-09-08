# -*- coding: utf-8 -*-
"""Ollama provider — 한글 왕복과 코드펜스 파싱.

2026-09-08 스파이크에서 실제로 밟은 두 함정을 고정한다.
 1) PowerShell 로 부르면 한글이 mojibake 가 되어 브리프가 통째로 무시된다.
    ("AI 광고영상" 을 넣었는데 화장품 세럼 제품샷이 나왔다)
 2) format:"json" 을 줘도 ```json 펜스로 감싸 온다.
"""
import json
import sys
from pathlib import Path

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import copy_engine as C


def test_loads_loose_reads_bare_json():
    assert C._loads_loose('{"a": 1}') == {"a": 1}


def test_loads_loose_reads_fenced_json():
    """```json 펜스로 감싸 와도 읽어야 한다(실측)."""
    txt = '```json\n{"prompt": "abc", "negative_prompt": "def"}\n```'
    assert C._loads_loose(txt)["prompt"] == "abc"


def test_loads_loose_raises_on_garbage():
    import pytest
    with pytest.raises(json.JSONDecodeError):
        C._loads_loose("no json here")


def test_call_ollama_sends_utf8_korean(monkeypatch):
    """요청 본문이 UTF-8 이고, 한글이 깨지지 않아야 한다."""
    seen = {}

    class _Resp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"response": '{"ok": "예"}'}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        seen["body"] = req.data
        seen["ctype"] = req.headers.get("Content-type", "")
        return _Resp()

    monkeypatch.setattr(C.urllib.request, "urlopen", fake_urlopen)
    out = C._call_ollama("광고 영상 서비스 브리프")

    body = json.loads(seen["body"].decode("utf-8"))
    assert "광고 영상 서비스 브리프" in body["prompt"]   # mojibake 회귀 방지
    assert body["format"] == "json"
    assert body["stream"] is False
    assert "utf-8" in seen["ctype"].lower()
    assert out == '{"ok": "예"}'


def test_call_llm_dispatches_to_ollama(monkeypatch):
    import config
    monkeypatch.setattr(config, "COPY_PROVIDER", "ollama")
    monkeypatch.setattr(C, "_call_ollama", lambda p: "OLLAMA")
    assert C._call_llm("x") == "OLLAMA"


def test_call_llm_still_defaults_to_gemini(monkeypatch):
    """회귀 방지 — 기존 동작이 그대로여야 한다."""
    import config
    monkeypatch.setattr(config, "COPY_PROVIDER", "gemini")
    monkeypatch.setattr(C, "_call_gemini", lambda p: "GEMINI")
    assert C._call_llm("x") == "GEMINI"
