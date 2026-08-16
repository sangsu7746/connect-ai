import httpx
import pytest
from core import gemini

def _resp(status, text="응답"):
    body = {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    return httpx.Response(status, json=body if status == 200 else {"error": {}},
                          request=httpx.Request("POST", "u"))

def test_generate_falls_back_on_failure(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "k")
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(url)
        return _resp(500) if len(calls) == 1 else _resp(200, "폴백 성공")
    monkeypatch.setattr(httpx, "post", fake_post)
    assert gemini.generate("p") == "폴백 성공"
    assert gemini.MODEL_CHAIN[0] in calls[0] and gemini.MODEL_CHAIN[1] in calls[1]

def test_generate_raises_when_all_fail(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "k")
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, headers=None, timeout=None: _resp(500))
    with pytest.raises(gemini.GeminiError):
        gemini.generate("p")

def test_generate_sends_key_in_header_not_url(monkeypatch):
    # M3: 키가 URL 쿼리에 노출되던 것을 헤더로 옮겼다. 로그·프록시에 키가 남지 않는다.
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "secret-key")
    seen = {}
    def fake_post(url, json=None, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        return _resp(200, "ok")
    monkeypatch.setattr(httpx, "post", fake_post)
    gemini.generate("p")
    assert "secret-key" not in seen["url"] and "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "secret-key"

def test_generate_without_key_raises(monkeypatch):
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "")
    with pytest.raises(gemini.GeminiError):
        gemini.generate("p")

def test_parse_json_variants():
    assert gemini.parse_json('```json\n[{"a": 1}]\n```') == [{"a": 1}]
    assert gemini.parse_json('앞말 [1, 2] 뒷말') == [1, 2]
    assert gemini.parse_json('{"b": 2}') == {"b": 2}
    with pytest.raises(ValueError):
        gemini.parse_json("json 없음")


def test_thinking_headroom_added_to_token_cap(monkeypatch):
    """사고 모델은 maxOutputTokens를 사고+본문에 함께 쓴다 — 호출자 예산에
    여유분을 더해 보내지 않으면 본문이 잘려 JSON 파싱이 깨진다(2026-08-17 실측)."""
    monkeypatch.setattr(gemini.settings, "gemini_api_key", "k")
    seen = {}

    def fake_post(url, json=None, headers=None, timeout=None):
        seen["cap"] = json["generationConfig"]["maxOutputTokens"]
        return _resp(200, "ok")

    monkeypatch.setattr(httpx, "post", fake_post)
    gemini.generate("p", max_tokens=512)
    assert seen["cap"] == 512 + gemini.THINKING_HEADROOM


def test_model_chain_has_no_retired_models():
    """gemini-1.5-flash·2.5-flash는 404(신규 사용자 불가) — 체인에 두면
    폴백이 전부 실패한다."""
    assert "gemini-1.5-flash" not in gemini.MODEL_CHAIN
    assert "gemini-2.5-flash" not in gemini.MODEL_CHAIN
    assert gemini.MODEL_CHAIN[0] == "gemini-3.5-flash"
