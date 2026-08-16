"""Gemini REST 클라이언트. SDK 없이 httpx 직접 호출, 모델 체인 폴백 (spec §7)."""
import json
import re

import httpx

from .config import settings

MODEL_CHAIN = ["gemini-3.5-flash", "gemini-flash-latest", "gemini-3.6-flash"]
_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

#: 사고(thinking) 모델 여유분. maxOutputTokens는 사고 토큰과 본문 토큰을 함께 세므로,
#: 호출자가 요청한 본문 예산에 이만큼을 더해 보낸다. 이걸 안 하면 사고가 한도를 다 먹고
#: 본문이 잘려(finishReason=MAX_TOKENS) JSON 파싱이 깨진다 — 2026-08-17 실측:
#: 릴스 7씬 배치에서 사고 3,928 / 본문 164 토큰으로 잘려 대본 생성이 전면 실패했다.
#: 한도는 상한일 뿐 실제 생성분만 과금되므로 넉넉히 잡아도 비용 영향은 없다.
THINKING_HEADROOM = 8192


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
                      "generationConfig": {
                          "temperature": temperature,
                          "maxOutputTokens": max_tokens + THINKING_HEADROOM}},
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
