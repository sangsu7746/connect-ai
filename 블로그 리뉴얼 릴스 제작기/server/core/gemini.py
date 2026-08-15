"""Gemini REST 클라이언트. SDK 없이 httpx 직접 호출, 모델 체인 폴백 (spec §7)."""
import json
import re

import httpx

from .config import settings

MODEL_CHAIN = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-flash"]
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class GeminiError(RuntimeError):
    pass


def available() -> bool:
    return bool(settings.gemini_api_key)


def generate(prompt: str, temperature: float = 0.8, max_tokens: int = 4096) -> str:
    if not available():
        raise GeminiError("GEMINI_API_KEY 미설정")
    last = None
    for model in MODEL_CHAIN:
        try:
            r = httpx.post(
                _URL.format(model=model),
                json={"contents": [{"parts": [{"text": prompt}]}],
                      "generationConfig": {"temperature": temperature,
                                           "maxOutputTokens": max_tokens}},
                headers={"x-goog-api-key": settings.gemini_api_key},
                timeout=60)
            if r.status_code != 200:
                last = f"{model}: HTTP {r.status_code}"
                continue
            parts = r.json()["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return text
            last = f"{model}: 빈 응답"
        except Exception as e:
            last = f"{model}: {type(e).__name__}"
    raise GeminiError(f"모든 모델 실패 — {last}")


def parse_json(text: str):
    """모델 출력에서 JSON을 꺼낸다. ```json 펜스·앞뒤 잡담 허용."""
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.M)
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        pass
    for opener, closer in (("[", "]"), ("{", "}")):
        start = t.find(opener)
        end = t.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except (json.JSONDecodeError, ValueError):
                continue
    raise ValueError("JSON을 찾지 못했다")
