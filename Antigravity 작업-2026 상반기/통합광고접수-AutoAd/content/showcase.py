# -*- coding: utf-8 -*-
"""showcase.py — 콘텐츠형 소재: 제품이 실제로 만들어낸 결과물을 보여준다

왜 필요한가:
  브랜드 카드(배너)는 어느 모임에서나 '광고'로 읽힌다. 주제 중심 모임에서는
  그 자체로 규칙 위반이 되거나 승인 대기에 걸린다(실측).
  반대로 **제품이 만든 결과물**은 그 모임의 주제에 맞는 내용이라 환영받는다.

무엇을 만드는가:
  실제 생성 결과 4장을 한 장의 격자 이미지로 묶는다. 브랜드 배너가 아니다.
  출처(도구 이름·주소)는 하단에 작게 밝힌다 — 숨기지 않는다.
  ⚠ 만든 사람이 누구인지 감추면 안 된다. 걸리면 계정이 날아가고, 그게 맞다.

사용:
  from content import showcase
  showcase.make(profile_key="inkcraft", channel="facebook")
"""
import io
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import config

# 업종별 '무엇을 보여줄 것인가'. 결과물 자체를 보여주는 게 핵심이다.
SPECS = {
    "inkcraft": {
        "label": "타투 도안",
        # 기법(스타일)과 소재(모티프)를 분리한다.
        # ⚠ 소재를 프롬프트에 박아두면 몇 번을 돌려도 같은 늑대·제비가 나온다.
        #   같은 그림을 여러 그룹에 뿌리면 사람도 플랫폼도 '같은 글'로 본다.
        "styles": [
            ("블랙워크", "bold blackwork tattoo design of {subject}, heavy black ink, "
                       "high contrast, clean white background, flash sheet style"),
            ("라인워크", "fine single-line minimal tattoo design of {subject}, "
                       "thin delicate lines, clean white background"),
            ("올드스쿨", "traditional american old school tattoo design of {subject}, "
                       "bold outlines, limited flat colors, clean white background"),
            ("도트워크", "dotwork stippling tattoo design of {subject}, "
                       "black dots shading only, clean white background"),
        ],
        "motifs": [
            "a wolf head with a geometric moon",
            "a crescent moon with small wildflowers",
            "a swallow and a rose",
            "a mountain range inside a circle",
            "a koi fish among curling waves",
            "a snake coiled around a dagger",
            "an owl perched on a bare branch",
            "a lighthouse with crashing waves",
            "a hummingbird and a trumpet flower",
            "a compass rose with a sailing ship",
            "a stag head with antlers and pine branches",
            "a butterfly with stained-glass wing patterns",
            "a phoenix rising from flames",
            "a hand holding a blooming lotus",
            "a whale breaching under a starry sky",
            "a fox curled among fern leaves",
        ],
    },
}


def _font(size: int):
    for name in ("malgunbd.ttf", "malgun.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _gen_one(prompt: str, model: str = None) -> bytes:
    from google import genai
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    r = client.models.generate_content(
        model=model or config.CARD_MODEL,
        contents=[prompt + "\n\nNo text, no letters, no watermark. Design only."])
    for cand in (r.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                return inline.data
    raise RuntimeError("이미지가 반환되지 않음")


def make(profile_key: str = None, channel: str = "facebook",
         out_path: str = None, model: str = None, variant: int = 0) -> dict:
    """결과물 격자 이미지 1장을 만든다. 반환 {path, styles}

    variant: 채널마다 다른 그림을 뽑기 위한 번호.
      같은 이미지를 여러 그룹에 올리면 발행 게이트(이미지 쿨다운)가 막고,
      막지 않더라도 플랫폼이 가장 빨리 잡는 패턴이다."""
    key = profile_key or config.PROFILE_KEY
    spec = SPECS.get(key)
    if not spec:
        raise ValueError(f"{key} 업종은 아직 콘텐츠형 소재를 지원하지 않습니다")

    size = 620                       # 각 칸 크기
    pad = 14
    tiles, names = [], []
    motifs = spec.get("motifs") or [""]
    for i, (label, prompt) in enumerate(spec["styles"]):
        # 변형마다 (기법, 소재) 조합이 겹치지 않게 건너뛴다.
        # ⚠ 스타일 수(4)의 배수로 건너뛰면 variant 가 한 바퀴 돌 때 조합이
        #   통째로 반복된다. 5는 16과 서로소라 8개 변형까지 전부 다르다.
        subject = motifs[(variant * 5 + i) % len(motifs)]
        p = prompt.replace("{subject}", subject) if subject else prompt
        print(f"[showcase] {label} · {subject or '기본'} 생성 중...")
        img = Image.open(io.BytesIO(_gen_one(p, model))).convert("RGB")
        # 정사각으로 잘라 격자를 고르게
        w, h = img.size
        m = min(w, h)
        img = img.crop(((w - m) // 2, (h - m) // 2, (w + m) // 2, (h + m) // 2))
        tiles.append(img.resize((size, size), Image.LANCZOS))
        names.append(label)

    grid_w = size * 2 + pad * 3
    foot = 92
    canvas = Image.new("RGB", (grid_w, size * 2 + pad * 3 + foot), (255, 255, 255))
    for i, t in enumerate(tiles):
        x = pad + (i % 2) * (size + pad)
        y = pad + (i // 2) * (size + pad)
        canvas.paste(t, (x, y))

    d = ImageDraw.Draw(canvas)
    # 각 칸에 스타일 이름만 작게 (제품 문구가 아니라 '무엇인지' 설명)
    f_tag = _font(30)
    for i, nm in enumerate(names):
        x = pad + (i % 2) * (size + pad) + 12
        y = pad + (i // 2) * (size + pad) + size - 46
        d.rectangle([x - 8, y - 6, x + f_tag.getlength(nm) + 12, y + 40],
                    fill=(255, 255, 255))
        d.text((x, y), nm, font=f_tag, fill=(30, 30, 35))

    # 출처 표기 — 작게, 그러나 분명히. 숨기지 않는다.
    fy = size * 2 + pad * 3
    d.rectangle([0, fy, grid_w, canvas.height], fill=(246, 246, 248))
    site = (config.BRAND_SITE or "").strip()
    d.text((pad + 6, fy + 16),
           f"AI로 생성한 {spec['label']} 예시 · {site}",
           font=_font(30), fill=(70, 70, 78))
    dis = (config.DISCLAIMER or "").strip()
    if dis:
        d.text((pad + 6, fy + 56), dis[:70], font=_font(22), fill=(120, 120, 128))

    out = Path(out_path) if out_path else (
        config.CREATIVES_DIR / f"showcase_{key}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, quality=94)
    print(f"[showcase] 완성: {out.name} ({canvas.width}x{canvas.height})")
    return {"path": str(out), "styles": names}
