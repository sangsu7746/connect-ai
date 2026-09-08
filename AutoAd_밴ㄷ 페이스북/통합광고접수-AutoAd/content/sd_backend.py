# -*- coding: utf-8 -*-
"""sd_backend.py — gemma4 가 쓴 영문 프롬프트로 로컬 SD 를 돌린다

왜 이렇게 나눴는가:
  SD 는 한글 글자를 못 그린다. 그래서 SD 에게는 '배경/도안' 만 맡기고
  한글은 Pillow 가 찍는다. 그 결과 AI 가 본문에 오타를 내던 문제
  ('상황'→'상형', '전문 컨설팅'→'전룬 건설형')가 구조적으로 사라진다.

2026-09-08 스파이크에서 밟은 함정 세 가지가 이 파일에 박혀 있다:
  · 인물 편향  — DreamShaper_8 은 무엇을 요구하든 인물로 끌고 간다.
                 NEG_FORCE 를 LLM 출력 뒤에 **항상** 덧붙인다.
  · 배경 불복  — "pure white background" 를 넣어도 사진 배경이 나온다.
                 프롬프트를 믿지 않고 is_clean_white 로 검사해 재시도한다.
  · 공간 지시  — SD1.5 는 "어디를 비워라" 를 못 지킨다. 여백은 여기서
                 해결하지 않는다. 호출부(Pillow)가 불투명 패널로 확보한다.
"""
import io
import json
import time
import base64
import urllib.request

from PIL import Image

import config
from content import copy_engine

# ⚠ LLM 이 무엇을 내놓든 코드가 뒤에 붙인다. 모델은 이걸 빠뜨릴 수 있고,
#   실제로 빠뜨려서 인물 사진이 나왔다.
NEG_FORCE = (
    "person, people, woman, man, face, portrait, human, hands, body, skin, "
    "text, letters, words, korean text, watermark, signature, typography, "
    "logo, caption, ui, numbers"
)

_PERSONA = """너는 세계 최고의 Stable Diffusion 프롬프트 엔지니어다.
아래 [브리프]를 읽고 SD1.5(DreamShaper)용 영어 프롬프트를 만든다.

⚠ 프롬프트의 주제는 반드시 [브리프]에서 나와야 한다. 일반적인 광고 이미지
  (화장품 제품샷·음식 사진 등)로 대체하지 마라.

반드시 포함할 요소:
1. 주제 및 동작 — 브리프를 시각화한 상세한 묘사
2. 배경 및 환경 — 빛의 각도, 분위기
3. 스타일 및 퀄리티 — photorealistic / digital art / flat illustration 등
4. 카메라·렌더 — wide angle, 85mm lens, depth of field, studio render 등
5. Negative Prompt — 퀄리티를 떨어뜨리는 요소

★ 이 이미지 위에는 한글 문구를 따로 얹는다. 그러므로:
(a) 이미지 안에 글자가 있으면 안 된다
(b) 사람·얼굴·손이 나오면 안 된다
(c) 지정된 화면 비율({w}x{h})에 맞는 구도로 만들어라
(d) 과장 광고 표현(폭발적 성장 그래프·트로피·1등 배지)을 넣지 마라

출력은 JSON 하나만:
{"prompt": "...", "negative_prompt": "..."}"""


def _ask_llm(brief: str, width: int, height: int) -> dict:
    """gemma4 에게 프롬프트를 받는다. 테스트에서 갈아끼우는 이음매다."""
    persona = _PERSONA.replace("{w}", str(width)).replace("{h}", str(height))
    raw = copy_engine._call_ollama(f"[브리프]\n{brief}\n\n---\n\n{persona}")
    return copy_engine._loads_loose(raw)


def build_prompt(brief: str, width: int, height: int) -> dict:
    d = _ask_llm(brief, width, height)
    neg = (d.get("negative_prompt") or "").strip()
    return {
        "prompt": (d.get("prompt") or "").strip(),
        "negative_prompt": (neg + ", " + NEG_FORCE) if neg else NEG_FORCE,
    }


def txt2img(prompt: str, negative: str, width: int, height: int) -> Image.Image:
    payload = {
        "prompt": prompt, "negative_prompt": negative,
        "width": width, "height": height,
        "steps": config.SD_STEPS, "cfg_scale": config.SD_CFG,
        "sampler_name": config.SD_SAMPLER, "scheduler": "Karras",
    }
    req = urllib.request.Request(
        f"{config.SD_WEBUI_URL}/sdapi/v1/txt2img",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=900) as r:
        body = json.loads(r.read().decode("utf-8"))
    return Image.open(io.BytesIO(base64.b64decode(body["images"][0]))).convert("RGB")


def is_clean_white(img: Image.Image, thresh: int = 235, band: float = 0.06) -> bool:
    """테두리가 흰색인가. 아니면 배경 지시를 어긴 것이다.

    ⚠ 가운데를 보면 안 된다. 도안은 가운데 있어야 정상이다. 테두리만 본다.
    ⚠ 평균만 보면 한쪽 모서리만 검은 비네트를 놓친다 — 최솟값도 같이 본다.
    """
    g = img.convert("L")
    w, h = g.size
    bw = max(1, int(min(w, h) * band))
    px = g.load()
    vals = []
    for x in range(w):
        for y in range(bw):
            vals.append(px[x, y])
            vals.append(px[x, h - 1 - y])
    for y in range(h):
        for x in range(bw):
            vals.append(px[x, y])
            vals.append(px[w - 1 - x, y])
    if not vals:
        return False
    avg = sum(vals) / len(vals)
    return avg >= thresh and min(vals) >= thresh - 60


def gen_tile(brief: str, size: int = 768, retries: int = 2) -> Image.Image:
    """게이트를 통과한 타일 1장. 실패하면 RuntimeError.

    재시도 비용은 13초뿐이라(실측) 버리고 다시 뽑는 편이 싸다.
    """
    last = None
    for attempt in range(retries + 1):
        p = build_prompt(brief, size, size)
        img = txt2img(p["prompt"], p["negative_prompt"], size, size)
        if is_clean_white(img):
            return img
        last = img
        print(f"[sd] 흰 배경 게이트 실패 — 재시도 {attempt + 1}/{retries}")
    raise RuntimeError(f"흰 배경 타일을 {retries + 1}회 시도에도 못 만들었습니다")


def warmup() -> float:
    """첫 장 지연을 없앤다. 모델이 메모리에서 밀려나 있으면 첫 요청이 느리다.

    실측(2026-09-08): 10시간 유휴 뒤에도 5.3초였다. 그래도 배치 앞에 한 번 부른다.
    """
    t0 = time.time()
    try:
        txt2img("a plain white square", NEG_FORCE, 256, 256)
    except Exception as e:
        print(f"[sd] 예열 실패(무시): {type(e).__name__}: {e}")
    return time.time() - t0
