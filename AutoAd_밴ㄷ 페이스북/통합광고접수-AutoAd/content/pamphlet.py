# ============================================================
#  content/pamphlet.py — 팜플렛(전단) 이미지 생성  (P1-2)
#  배경 2모드:
#    · solid     : 브랜드 그라디언트 (네트워크/크레딧 불필요·가장 깔끔·기본)
#    · printcraft: PrintCraft 로컬 서버 /api/generate 로 AI 배경(옵션)
#  텍스트: Pillow 로 헤드라인 + 본문 + CTA + 의무표기(하단 고정층) 합성
#  ⚠ 의무표기(disclosures)는 항상 고정 텍스트층 — AI 렌더 텍스트로 대체 금지.
# ============================================================
import io
import base64
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageEnhance

import config

PRINTCRAFT_GENERATE = f"{config.PRINTCRAFT_BASE}/api/generate"

# 한글 폰트 (Windows 맑은 고딕). 없으면 기본 폰트로 폴백.
_FONT_DIR = Path("C:/Windows/Fonts")
_FONT_BOLD = _FONT_DIR / "malgunbd.ttf"
_FONT_REG = _FONT_DIR / "malgun.ttf"

# 브랜드 팔레트 (설계서와 동일 톤: teal-ink)
BRAND = {
    "bg_top":    (16, 32, 42),
    "bg_bottom": (9, 95, 89),
    "glow":      (18, 124, 116),
    "ink":       (255, 255, 255),
    "muted":     (208, 227, 224),
    "accent":    (14, 140, 130),
    "disc_bg":   (9, 16, 18),
    "disc_ink":  (198, 210, 212),
}

# PrintCraft 유효 style 키 (POD 프리셋). 배경 텍스처 용도로 추상 계열 권장.
DEFAULT_STYLE = "geometric"


# ── 폰트 ────────────────────────────────────────────────────
def _drawable(text: str, font=None) -> str:
    """맑은 고딕이 못 그리는 문자를 제거한다.

    ⚠ 이모지(🌐 U+1F310 등)는 글리프가 없어 두부(□)로 찍힌다 — 실제 발생한 문제.
      PIL 의 getmask/bbox 로는 감지가 안 된다(없는 글자에 .notdef 박스를 그려 bbox 가 잡힘).
      그래서 '이모지 평면(BMP 밖, U+10000 이상)과 알려진 미지원 기호'를 문자값으로 걸러낸다.
      ☎(U+260E)·※·· 같은 BMP 기호는 맑은 고딕에 있으므로 유지된다."""
    f = font or _font(40, bold=True)
    notdef = _notdef_signature(f)
    out = []
    for ch in str(text or ""):
        if ord(ch) >= 0x10000:              # 보조평면(대부분의 이모지) → 두부 확정
            continue
        if ch.isspace() or ch.isalnum():
            out.append(ch)
            continue
        try:
            if _glyph_signature(f, ch) == notdef:   # .notdef(두부)와 똑같이 그려지면 없는 글자
                continue
        except Exception:
            pass
        out.append(ch)
    return "".join(out).strip()


def _glyph_signature(font, ch: str):
    m = font.getmask(ch)
    return (m.size, bytes(m))


def _notdef_signature(font):
    """확실히 없는 글자를 그려 '두부' 모양의 기준을 얻는다."""
    try:
        return _glyph_signature(font, "")     # 사용자 정의 영역 = 폰트에 없음
    except Exception:
        return None


def _font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    path = _FONT_BOLD if bold else _FONT_REG
    try:
        return ImageFont.truetype(str(path), size)
    except Exception:
        return ImageFont.load_default()


class FontUnavailable(RuntimeError):
    """법정 의무표기를 그릴 한글 폰트를 못 찾았다."""


class GlyphUnavailable(RuntimeError):
    """법정 의무표기 안에 폰트가 못 그리는 글자가 있다."""


def _drawable_strict(text: str, font=None) -> str:
    """의무표기 전용 - 글자가 하나라도 지워지면 **터진다**.

    _drawable() 은 글리프가 없는 문자를 말없이 버린다. 면책문구라면 보기
    흉한 정도지만 법정 문구에서는 다르다 - 운영자가 이자율에 전각 물결
    (U+FF5E) 이나 전각 퍼센트를 쓰면 그 글자만 사라져 '연 5.9%20.0%' 처럼
    **의미가 바뀐 이자율**이 인쇄된다. 조용한 삭제는 두부(tofu)와 같은
    실패 등급이므로 _font_strict() 와 같은 태도로 소재 생성을 중단시킨다."""
    src = str(text or "")
    out = _drawable(src, font)
    # _drawable 은 앞뒤 공백을 strip 하므로 그만큼은 비교에서 제외한다.
    if "".join(out.split()) != "".join(src.split()):
        dropped = "".join(sorted(set(src) - set(out)))
        raise GlyphUnavailable(
            "mandatory disclosure contains undrawable characters: "
            + " ".join(f"U+{ord(c):04X}" for c in dropped if not c.isspace()))
    return out


def _font_strict(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    """의무표기 전용 폰트 로더 - 실패하면 **조용히 폴백하지 않고 터진다**.

    _font() 는 실패 시 ImageFont.load_default() 로 떨어지는데, 그 폰트에는
    한글 글리프가 없어 문구가 통째로 깨진 채 저장된다. 면책문구라면 보기
    흉한 정도지만, 법정 필수기재사항이 깨져 나가면 그건 미표기와 같다.
    그래서 여기서는 소재 생성을 중단시킨다."""
    path = _FONT_BOLD if bold else _FONT_REG
    try:
        return ImageFont.truetype(str(path), size)
    except Exception as e:
        raise FontUnavailable(
            f"mandatory disclosure font not available: {path} ({type(e).__name__})"
        ) from e


# ── 배경 ────────────────────────────────────────────────────
def printcraft_generate(prompt: str, style: str = DEFAULT_STYLE,
                        engine: str = "standard", timeout: int = 120) -> bytes:
    """PrintCraft 로컬 서버로 배경 생성 → 이미지 bytes. 응답 image 는 data URL."""
    r = requests.post(PRINTCRAFT_GENERATE,
                      json={"prompt": prompt[:500], "style": style, "engine": engine},
                      timeout=timeout)
    r.raise_for_status()
    data_url = r.json().get("image", "")
    if "," not in data_url:
        raise ValueError("PrintCraft 응답에 image data URL 없음")
    return base64.b64decode(data_url.split(",", 1)[1])


def _gradient_bg(size) -> Image.Image:
    """세로 그라디언트 + 우상단 액센트 글로우."""
    w, h = size
    img = Image.new("RGB", size, BRAND["bg_top"])
    draw = ImageDraw.Draw(img)
    top, bot = BRAND["bg_top"], BRAND["bg_bottom"]
    for y in range(h):
        t = y / max(1, h - 1)
        color = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
        draw.line([(0, y), (w, y)], fill=color)
    # 부드러운 액센트 글로우 (반투명 원 → 블러)
    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    r = int(min(w, h) * 0.5)
    gd.ellipse([w - r, -r // 2, w + r // 2, r], fill=BRAND["glow"] + (90,))
    from PIL import ImageFilter
    glow = glow.filter(ImageFilter.GaussianBlur(int(min(w, h) * 0.12)))
    img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")
    return img


def _cover(img: Image.Image, size) -> Image.Image:
    """비율 유지하며 size 를 꽉 채우도록 리사이즈 후 중앙 크롭."""
    tw, th = size
    w, h = img.size
    scale = max(tw / w, th / h)
    nw, nh = int(w * scale), int(h * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    x, y = (nw - tw) // 2, (nh - th) // 2
    return img.crop((x, y, x + tw, y + th))


def _load_background(size, prompt=None, style=DEFAULT_STYLE,
                     engine="standard", mode="solid") -> Image.Image:
    if mode == "printcraft" and prompt:
        try:
            raw = printcraft_generate(prompt, style, engine)
            bg = Image.open(io.BytesIO(raw)).convert("RGB")
            bg = _cover(bg, size)
            return ImageEnhance.Brightness(bg).enhance(0.5)   # 가독성 위해 어둡게
        except Exception as e:
            print(f"[pamphlet] PrintCraft 실패 → 그라디언트 폴백: {e}")
    return _gradient_bg(size)


# ── 텍스트 배치 ─────────────────────────────────────────────
def _wrap(draw, text: str, font, max_w: int) -> list:
    """폭 기준 줄바꿈 (한글=공백 없이도 글자 단위로 접힘)."""
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= max_w:
                cur += ch
            else:
                if cur:
                    lines.append(cur)
                cur = ch
        lines.append(cur)
    return lines


def compose_pamphlet(bg: Image.Image, copy: dict, channel: str,
                     disclosures: str, out_path: str = None) -> str:
    """배경 + 카피 + CTA + 의무표기 합성 → PNG 저장, 경로 반환. (네트워크 없음)"""
    img = bg.convert("RGB").copy()
    W, H = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    pad = int(W * 0.07)
    maxw = W - pad * 2

    # 헤드라인
    hl_font = _font(int(W * 0.072), bold=True)
    y = int(H * 0.09)
    for ln in _wrap(draw, copy.get("headline", ""), hl_font, maxw):
        draw.text((pad, y), ln, font=hl_font, fill=BRAND["ink"])
        y += int(hl_font.size * 1.22)

    # 본문
    y += int(H * 0.025)
    bd_font = _font(int(W * 0.037), bold=False)
    for ln in _wrap(draw, copy.get("body", ""), bd_font, maxw):
        draw.text((pad, y), ln, font=bd_font, fill=BRAND["muted"])
        y += int(bd_font.size * 1.5)

    # CTA 버튼
    cta = copy.get("cta", "").strip()
    if cta:
        cta_font = _font(int(W * 0.044), bold=True)
        tw = draw.textlength(cta, font=cta_font)
        bx0, by0 = pad, int(H * 0.73)
        bx1 = bx0 + tw + int(W * 0.09)
        by1 = by0 + cta_font.size + int(H * 0.035)
        draw.rounded_rectangle([bx0, by0, bx1, by1],
                               radius=int(H * 0.018), fill=BRAND["accent"])
        draw.text((bx0 + int(W * 0.045), by0 + int(H * 0.017)),
                  cta, font=cta_font, fill=BRAND["ink"])

    # 의무표기 하단 고정층 (컴플라이언스)
    disc_font = _font(int(W * 0.021), bold=False)
    disc_lines = _wrap(draw, disclosures, disc_font, maxw)
    line_h = int(disc_font.size * 1.4)
    band_h = line_h * len(disc_lines) + int(H * 0.035)
    draw.rectangle([0, H - band_h, W, H], fill=BRAND["disc_bg"])
    yy = H - band_h + int(H * 0.017)
    for ln in disc_lines:
        draw.text((pad, yy), ln, font=disc_font, fill=BRAND["disc_ink"])
        yy += line_h

    out = Path(out_path) if out_path else (config.CREATIVES_DIR / f"pamphlet_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"[pamphlet] 저장: {out} ({W}x{H})")
    return str(out)


def render_pamphlet(copy: dict, channel: str, disclosures: str,
                    prompt: str = None, style: str = DEFAULT_STYLE,
                    engine: str = "standard", bg_mode: str = "solid",
                    out_path: str = None) -> str:
    """
    (커스텀 생성 경로) 배경 위에 카피 합성. 신규 상품/변형용.
    copy: {headline, body, cta} · bg_mode: 'solid' | 'printcraft'
    """
    size = config.CHANNEL_SPECS.get(channel, (1080, 1080))
    bg = _load_background(size, prompt=prompt or copy.get("headline"),
                          style=style, engine=engine, mode=bg_mode)
    return compose_pamphlet(bg, copy, channel, disclosures, out_path)


# ── 템플릿 모드 (기존 더스틴홀딩스 전단 재사용 — 기본 경로) ──────────
from content import registry


def _overlay_promo(img: Image.Image, promo: str):
    """상단 우측에 얇은 프로모 리본(선택). 원 디자인은 건드리지 않음."""
    W, H = img.size
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font(int(W * 0.028), bold=True)
    tw = draw.textlength(promo, font=font)
    pad = int(W * 0.02)
    x1, y1 = W - int(W * 0.03), int(H * 0.02)
    x0 = x1 - tw - pad * 2
    y0 = y1
    draw.rounded_rectangle([x0, y0, x1, y0 + font.size + pad],
                           radius=int(font.size * 0.4), fill=(196, 122, 30, 235))
    draw.text((x0 + pad, y0 + pad // 2), promo, font=font, fill=(255, 255, 255))


# ── 설명서 → 광고 카드 (기성 전단이 없는 업종용) ────────────
def brief_from_doc(doc_path: str) -> dict:
    """제품 설명서(PDF/이미지)를 읽어 광고 브리프를 뽑는다.
    ⚠ '설명서에 있는 내용만' 쓰도록 지시한다 — 없는 기능·수치를 지어내면 허위광고가 된다."""
    from google import genai
    from google.genai import types
    import json as _json

    # ⚠ 이 함수는 render_from_doc 의 앞단이다. 카드 이미지 경로 전체를 잠근다.
    if getattr(config, "IMAGE_GEN_LOCKED", False):
        raise RuntimeError(
            "이미지 생성이 잠겨 있습니다(IMAGE_GEN_LOCKED=1). "
            "풀려면 .env 에서 IMAGE_GEN_LOCKED=0 으로 바꾸세요.")
    p = Path(doc_path)
    mime = "application/pdf" if p.suffix.lower() == ".pdf" else "image/png"
    schema = ('{"product":"제품명","headline":"헤드라인(15자내)","sub":"보조문구(25자내)",'
              '"benefits":["핵심혜택1","핵심혜택2","핵심혜택3"],'
              '"audience":"주요 타깃","tone":"어울리는 톤","visual":"카드에 어울리는 비주얼 묘사"}')
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    r = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[types.Part.from_bytes(data=p.read_bytes(), mime_type=mime),
                  "이 제품 설명서를 읽고 SNS 광고 카드용 브리프를 뽑아라.\n"
                  "설명서에 실제로 있는 내용만 쓰고, 없는 기능·수치·효과는 절대 지어내지 마라.\n"
                  f"금지 표현: {', '.join(config.BANNED_PHRASES) or '(없음)'}\n"
                  f"업종 주의: {config.COMPLIANCE_NOTE}\n다음 JSON 형식으로만 답하라:\n" + schema],
        config=types.GenerateContentConfig(temperature=0.4,
                                           response_mime_type="application/json"),
    )
    return _json.loads(r.text)


def render_from_doc(doc_path: str = None, channel: str = "band", promo: str = None,
                    model: str = None, stamp: bool = True, out_path: str = None) -> dict:
    """설명서 → 브리프 → 카드 이미지. 전단이 없는 업종의 기본 경로.
    글자를 적게 넣을수록 오타가 줄어든다(실측) → 헤드라인+보조+혜택3 으로 제한."""
    from google import genai
    from google.genai import types

    doc_path = doc_path or config.DEFAULT_DOC
    if not doc_path or not Path(doc_path).exists():
        raise FileNotFoundError(
            f"설명서를 찾을 수 없습니다: {doc_path or '(미지정)'}\n"
            f"  프로필({config.PROFILE_KEY})의 content.doc 또는 인자로 경로를 주세요.")
    brief = brief_from_doc(doc_path)
    ratio = CARD_RATIO.get(channel, "정사각형(1:1)")
    extra = f"\n- 우측 상단에 '{promo}' 배지" if promo else ""
    tail = ("\n■ 넣지 말 것: 전화번호, 회사명, 로고, 하단 안내문구 (나중에 따로 붙입니다)"
            if stamp else "")
    prompt = (
        f"{ratio} SNS 광고 카드를 디자인해 주세요.\n\n"
        f"제품: {brief.get('product','')}\n"
        f"헤드라인(크게): {brief.get('headline','')}\n"
        f"보조문구: {brief.get('sub','')}\n"
        f"핵심 혜택: {' / '.join(brief.get('benefits', []))}\n"
        f"타깃: {brief.get('audience','')}\n톤: {brief.get('tone','')}\n"
        f"비주얼: {brief.get('visual','')}" + extra + tail +
        # ⚠ 실측: 작은 글씨가 많은 표·UI 목업에서 한글이 대량으로 뭉개진다
        #   (예: '맞춤'→'맞촘', '단가'→'던기비', '네이버쇼핑'→'네이버스핑')
        #   그래서 세밀한 표·스프레드시트·브라우저 UI 자체를 금지한다.
        "\n\n■ 렌더링 규칙(반드시 지킬 것):\n"
        "- 작은 글씨를 **절대** 넣지 마세요. 표·스프레드시트·가격표·브라우저 주소창·"
        "채팅 UI 등 잔글씨가 많은 목업은 만들지 마세요. 뭉개져서 못 씁니다.\n"
        "- 화면에 들어가는 한글 문장은 위에 준 것만. 그 밖의 글자를 지어내지 마세요.\n"
        "- 목업 안에 텍스트가 필요하면 글자 없이 도형·아이콘으로 표현하세요.\n"
        "- 지시문·제목·비율 표기 같은 **작업 지시 자체를 이미지에 그리지 마세요**.\n"
        "- 도메인 주소를 지어내지 마세요(하단에 정확한 주소가 따로 붙습니다).\n"
        "\n한글 맞춤법을 정확히 지켜 렌더링하세요. 텍스트는 최소한으로."
    )
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    r = client.models.generate_content(model=model or config.CARD_MODEL, contents=[prompt])

    data = None
    for cand in (r.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                data = inline.data
                break
        if data:
            break
    if not data:
        raise RuntimeError("이미지가 반환되지 않음")

    # 과금이 실제로 발생한 지점 — 하루 이미지 예산의 분모를 여기서 올린다.
    # ⚠ 소재 수가 아니라 이 지점을 세야 재사용·로컬 합성이 예산을 갉아먹지
    #   않는다(db.py 의 images_generated_today 주석 참고).
    # ⚠ 기록 실패로 이미 지불한 그림을 버리지 않는다.
    try:
        import db
        db.note_image_generated()
    except Exception as e:
        print(f"[pamphlet] 예산 카운터 기록 실패({type(e).__name__}: {e}) — 계속합니다")

    slug = Path(doc_path).stem[:30].replace(" ", "_")
    out = Path(out_path) if out_path else (config.CREATIVES_DIR / f"doc_{slug}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    if stamp:
        stamp_contact_band(data, out)
    else:
        out.write_bytes(data)
    print(f"[pamphlet] 설명서→카드: {out.name} ← {Path(doc_path).name}")
    return {"path": str(out), "brief": brief, "model": model or config.CARD_MODEL}


# ── 카드형 재편집 (기존 전단 → Gemini → 소셜 카드) ──────────
CARD_RATIO = {"band": "정사각형(1:1)", "cafe": "정사각형(1:1)",
              "facebook": "가로형(1.91:1)", "kakao": "세로형(4:5)"}


def _card_prompt(tpl: dict, channel: str, promo: str = None, stamp: bool = True) -> str:
    ratio = CARD_RATIO.get(channel, "정사각형(1:1)")
    extra = f"\n- 우측 상단에 '{promo}' 배지를 추가" if promo else ""

    if stamp:
        # 연락처·면책문구는 아래에서 직접 찍는다 → AI 에게 맡기지 않고, 중복도 막는다.
        tail = (
            "\n\n■ 넣지 말 것 (중요):\n"
            "- 전화번호, 회사명, 로고, 하단 면책문구는 **넣지 마세요**. 나중에 따로 붙입니다.\n"
            "- 하단 영역은 광고 내용으로 채우고, 연락처 자리는 비워두세요."
        )
    else:
        keep = [f"전화번호: {config.BRAND_PHONE}",
                f"회사명: {config.BRAND_COMPANY}",
                f"하단 작은 글씨: {config.LOAN_DISCLAIMER}"]
        if config.BRAND_REG_NO:
            keep.append(f"등록번호: {config.BRAND_REG_NO}")
        tail = ("\n\n■ 글자 하나도 바꾸지 말 것:\n" + "\n".join(f"- {k}" for k in keep))

    return (
        f"이 대출 광고 전단지를 **{ratio} 소셜미디어 카드**로 재구성해 주세요.\n\n"
        f"■ 유지할 것:\n- 제목: {tpl['title']}\n"
        "- 원본의 브랜드 색상(네이비/골드)과 분위기\n\n"
        "■ 바꿀 것:\n"
        "- 세로로 긴 포스터 → 카드 레이아웃으로 재배치\n"
        "- 정보를 줄이고 핵심만 남겨 모바일에서 읽기 쉽게" + extra + tail +
        "\n\n한글 맞춤법을 정확히 지켜 렌더링하세요. 없는 정보를 지어내지 마세요."
    )


def stamp_contact_band(image_bytes: bytes, out_path) -> str:
    """AI가 만든 카드 **위에** 연락처·회사명·면책문구를 직접 덧씌운다.

    왜 이렇게 하나:
      이미지 모델은 한글을 미묘하게 틀리게 렌더링한다(실측: '가치'→'가처',
      '홀딩스'→'흘딩스', '중개'→'증개'). 그리고 AI 로 다시 읽혀 검사하는 방법은
      읽기 모델이 깨진 글자를 자동 교정해 버려서 **오류를 못 잡는다**(실측 확인).
      따라서 법적으로 틀리면 안 되는 정보는 AI 에게 맡기지 않고 여기서 확정한다.
    """
    src = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    W, H0 = src.size

    pad = int(W * 0.045)
    f_tel = _font(int(W * 0.058), bold=True)
    f_co = _font(int(W * 0.030), bold=True)
    f_dis = _font(int(W * 0.021), bold=False)

    # 업종에 따라 연락 수단이 다르다.
    #   웹/앱 서비스 → 사이트 주소가 행동유도(전화번호 없음)
    #   오프라인 업체 → 전화번호
    # 프로필에 있는 것만 그린다. 둘 다 있으면 사이트를 크게, 전화는 회사 줄에.
    site = (config.BRAND_SITE or "").replace("https://", "").replace("http://", "").rstrip("/")
    if site:
        # ⚠ 🌐 같은 이모지는 맑은 고딕에 글리프가 없어 두부(□)로 찍힌다 → 기호 없이 URL만.
        tel_line = _drawable(site, f_tel)
        sub = [config.BRAND_COMPANY, config.BRAND_REGISTERED]
        if config.BRAND_PHONE:
            sub.append(f"☎ {config.BRAND_PHONE}")
    else:
        tel_line = _drawable(f"☎ {config.BRAND_PHONE}", f_tel) if config.BRAND_PHONE else ""
        sub = [config.BRAND_COMPANY, config.BRAND_REGISTERED]
    co_line = _drawable(" · ".join(x for x in sub if x), f_co)
    probe = ImageDraw.Draw(src)
    disc_lines = _wrap(probe, config.DISCLAIMER, f_dis, W - pad * 2) if config.DISCLAIMER else []

    band_h = pad
    if tel_line:
        band_h += int(f_tel.size * 1.35)
    if co_line:
        band_h += int(f_co.size * 1.5)
    band_h += int(f_dis.size * 1.45) * len(disc_lines)
    if band_h <= pad:
        # 찍을 게 아무것도 없으면 원본 그대로 저장
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        src.save(out, "PNG")
        return str(out)

    # ⚠ 띠를 이미지 위에 덮으면 AI가 그린 내용(아이콘·문구)이 잘린다.
    #   그래서 캔버스를 아래로 늘려 띠를 '덧붙인다' — 원본 손실 0.
    img = Image.new("RGB", (W, H0 + band_h), (9, 16, 18))
    img.paste(src, (0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    H = img.size[1]
    y = H0 + int(pad * 0.5)
    if tel_line:
        draw.text((pad, y), tel_line, font=f_tel, fill=(233, 197, 106))
        y += int(f_tel.size * 1.35)
    if co_line:
        draw.text((pad, y), co_line, font=f_co, fill=(255, 255, 255))
        y += int(f_co.size * 1.5)
    for ln in disc_lines:
        draw.text((pad, y), ln, font=f_dis, fill=(198, 210, 212))
        y += int(f_dis.size * 1.45)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    return str(out)


def verify_card_text(image_bytes: bytes, must_contain: list) -> dict:
    """(참고용) 문구 누락 여부만 대략 확인.

    ⚠ 신뢰하지 말 것 — 실측 결과 읽기 모델이 깨진 글자를 자동 교정해서
      '흘딩스'→'홀딩스', '가처'→'가치' 같은 **실제 오타를 통과시킨다**.
      법적으로 중요한 정보는 stamp_contact_band() 로 덧씌워 보장하고,
      최종 확인은 승인 콘솔에서 사람이 눈으로 한다."""
    import json as _json
    from google import genai
    from google.genai import types
    client = genai.Client(api_key=config.GEMINI_API_KEY)

    targets = _json.dumps(must_contain, ensure_ascii=False)
    prompt = (
        "당신은 인쇄 교정자입니다. 이미지 속 글자를 **한 글자씩** 대조하세요.\n"
        f"확인할 문구 목록: {targets}\n\n"
        "각 문구에 대해, 이미지에 **완전히 똑같은 글자**로 적혀 있는지 판정하세요.\n"
        "- 한 글자라도 다르면(예: 홀→흘, 중→증, 치→처) match=false 입니다.\n"
        "- 절대 교정하지 마세요. 이미지에 잘못 적혀 있으면 잘못된 그대로 actual 에 적으세요.\n"
        "- 아예 없으면 match=false, actual=\"\" 입니다.\n\n"
        '출력은 JSON 배열만: [{"target":"...","match":true/false,"actual":"화면에 보이는 실제 글자"}]'
    )
    resp = client.models.generate_content(
        model="gemini-flash-latest",
        contents=[types.Part.from_bytes(data=image_bytes, mime_type="image/png"), prompt],
        config=types.GenerateContentConfig(
            temperature=0, response_mime_type="application/json"),
    )
    try:
        rows = _json.loads(resp.text or "[]")
    except Exception:
        return {"ok": False, "missing": list(must_contain),
                "text": resp.text or "", "note": "판정 응답 파싱 실패 — 사람이 확인 필요"}

    bad = []
    for r in rows:
        if not r.get("match"):
            actual = (r.get("actual") or "").strip()
            bad.append(f"{r.get('target')}" + (f" → 실제 '{actual}'" if actual else " (없음)"))
    return {"ok": not bad, "missing": bad, "text": resp.text or ""}


def render_card(product_key: str, channel: str = "band", promo: str = None,
                model: str = None, stamp: bool = True, out_path: str = None) -> dict:
    """기존 전단을 Gemini 로 카드형 재편집.

    stamp=True(기본): 생성 결과 위에 연락처·회사명·면책문구를 직접 덧씌워
      **법적으로 중요한 정보가 AI 오타로 틀리는 일을 원천 차단**한다.
      (AI 자동 검증은 신뢰할 수 없음이 실측으로 확인됨 — verify_card_text 주석 참조)
    최종 확인은 승인 콘솔에서 사람이 눈으로 한다."""
    from google import genai
    from google.genai import types

    tpl = registry.get(product_key)
    src = tpl.get("flyer")
    if not src:
        raise FileNotFoundError(f"{product_key}: 원본 전단(JPG) 없음")

    if getattr(config, "IMAGE_GEN_LOCKED", False):
        raise RuntimeError(
            "이미지 생성이 잠겨 있습니다(IMAGE_GEN_LOCKED=1). "
            "풀려면 .env 에서 IMAGE_GEN_LOCKED=0 으로 바꾸세요.")
    mdl = model or config.CARD_MODEL
    client = genai.Client(api_key=config.GEMINI_API_KEY)
    resp = client.models.generate_content(
        model=mdl,
        contents=[types.Part.from_bytes(data=Path(src).read_bytes(), mime_type="image/jpeg"),
                  _card_prompt(tpl, channel, promo, stamp)],
    )

    data = None
    for cand in (resp.candidates or []):
        for part in (cand.content.parts or []):
            inline = getattr(part, "inline_data", None)
            if inline and inline.data:
                data = inline.data
                break
        if data:
            break
    if not data:
        raise RuntimeError(f"{mdl}: 이미지가 반환되지 않음")

    out = Path(out_path) if out_path else (
        config.CREATIVES_DIR / f"card_{product_key}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)

    if stamp:
        stamp_contact_band(data, out)      # 연락처·회사명·면책문구 확정
        note = "연락처·면책문구 덧씌움(오타 불가)"
    else:
        out.write_bytes(data)
        note = "⚠ 원본 그대로 — 오타 여부를 사람이 확인할 것"
    print(f"[pamphlet] 카드 생성: {out.name} ({mdl}) — {note}")
    return {"path": str(out), "model": mdl, "stamped": stamp}


# ── 의무표기 글자크기 (최종 폭 기준) ────────────────────────
# 두 기준이 **병존**하고 엄격한 쪽이 구속한다:
#   (a) 시행령 제6조의2 : 필수기재 문구는 상호 글자와 같거나 크게
#   (b) [별표1] 1.다    : 그 광고에 표시된 **최대글자의 3분의 1 이상**
# 이전 판본은 (a) 만 보고 0.036 을 썼는데, 실측하면 (b) 에 **미달**이었다.
#   기성 전단(1024x1536) 실측 - 헤드라인 '아파트/담보대출' 약 122px(= 폭의
#   약 0.119), 상호 '(주)더스틴홀딩스대부중개' 약 23px.
#   → (b) 가 요구하는 최소 = 122/3 = 40.7px. 0.036 은 36.8px 로 미달.
FLYER_MAX_GLYPH_RATIO = 0.12      # 최대글자 높이 / 이미지 폭 (전단 실측)
# 0.045 는 (b) 하한 0.040 위에 여유를 둔 값이다. 전단을 재제작해 헤드라인을
# 더 키우면 FLYER_MAX_GLYPH_RATIO 를 올려야 한다 - 코드는 원본 전단의 글자
# 크기를 스스로 알지 못하므로, 이 상수가 전단과 어긋나면 조용히 위반이 된다.
MANDATORY_FONT_RATIO = 0.045


def mandatory_font_px(width: int, max_glyph_ratio: float = None) -> int:
    """이 폭에서 의무표기가 가져야 하는 최소 글자 크기(px).

    max(설정 비율, 최대글자/3) - [별표1] 1.다 를 코드로 못박는 지점이다."""
    r = FLYER_MAX_GLYPH_RATIO if max_glyph_ratio is None else float(max_glyph_ratio)
    by_ratio = int(width * MANDATORY_FONT_RATIO)
    by_max_glyph = -(-int(width * r * 1000) // 3000)     # ceil(width*r/3)
    return max(12, by_ratio, by_max_glyph)


def _norm_line(s) -> str:
    """중복 판정용 정규화: 공백 전부 제거 + 끝 마침표 제거."""
    return "".join(str(s or "").split()).rstrip(".")


def _rel_luminance(rgb) -> float:
    def _ch(c):
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (_ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast_with_white(rgb) -> float:
    return 1.05 / (_rel_luminance(rgb) + 0.05)


def _contrast(a, b) -> float:
    la, lb = _rel_luminance(a), _rel_luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# 글자와 배경 사이 최소 명암비. WCAG AAA(7:1).
# 법정 문구는 '쉽게 구별되게'([별표1]) 읽혀야 하므로 본문용 AA(4.5:1)로는 모자란다.
BAND_MIN_CONTRAST = 7.0
BAND_INK_FALLBACK = (9, 16, 18)          # 전단에서 색을 못 뽑았을 때의 글자색
BAND_BG_FALLBACK = (238, 240, 241)       # 같은 경우의 배경(옅은 회색)
# 배경을 만들 때 잉크를 흰색과 섞는 비율. 1.0 이면 순백.
BAND_TINT = 0.93
# 전단과 띠 사이 구분선 두께(이미지 폭 대비).
BAND_RULE_RATIO = 0.004


def _flyer_ink(base: Image.Image, fallback=BAND_INK_FALLBACK) -> tuple:
    """전단에서 '진한 글씨'로 쓸 색을 뽑는다.

    자주 쓰인 색 중 **흰 바탕에서 7:1 이상**으로 읽히는 가장 흔한 색이다.
    보통 전단의 브랜드 남색·먹색이 잡힌다."""
    try:
        small = base.convert("RGB").resize((64, 64), Image.NEAREST)
    except Exception:
        return fallback
    counts = {}
    for px in small.getdata():
        counts[px] = counts.get(px, 0) + 1
    for px, _n in sorted(counts.items(), key=lambda kv: -kv[1]):
        if _contrast_with_white(px) >= BAND_MIN_CONTRAST:
            return px
    return fallback


def band_colors(base: Image.Image) -> tuple:
    """띠의 (배경, 글자, 구분선). **밝은 바탕 + 진한 글씨**.

    왜 밝은 바탕인가 — 예전에는 (9,16,18) 바탕에 흰 글자였다. 의무표기가
    이미지의 43%를 차지하는데 그 면적이 통째로 검은 덩어리라, 전단과 따로 노는
    판처럼 보였다(운영자 2026-08-11). 면적은 [별표1] 1.다(최대글자의 1/3 이상)
    때문에 줄일 수 없으므로, 같은 면적이 덜 무겁게 보이도록 명암을 뒤집는다.

    ⚠ 순백으로 칠하면 안 된다. 전단 자체가 흰 바탕이 약 15%라 띠가 전단에
      녹아버리고, 그러면 [별표1] 이 요구하는 '그 밖의 광고사항과 쉽게 구별되게'
      를 잃는다. 그래서 (a) 전단의 진한 색을 흰색과 섞은 **옅은 톤**을 쓰고
      (b) 전단과 띠 사이에 같은 진한 색으로 **구분선**을 긋는다.

    ⚠ 명암비가 7:1 에 못 미치면 예전 배색(진한 바탕 + 흰 글자)으로 떨어진다.
      법정 문구가 안 읽히는 것은 미표기와 다를 바 없다 - 읽힘이 먼저다.
    """
    ink = _flyer_ink(base)
    bg = tuple(int(round(c + (255 - c) * BAND_TINT)) for c in ink)
    if _contrast(bg, ink) >= BAND_MIN_CONTRAST:
        return bg, ink, ink
    # 옅은 톤으로 대비가 안 나오면(전단 색이 이미 밝은 경우) 예전 방식.
    return BAND_INK_FALLBACK, (255, 255, 255), (255, 255, 255)


def band_lines(lines: list, header: list = None) -> list:
    """하단 띠에 **실제로 그려지는** 줄 목록. 머리글과 겹치는 줄은 뺀다.

    [별표1] 1.가 는 상호·등록번호를 **왼쪽상단**(= header)에 요구하는데,
    disclosure.lines() 는 같은 값을 띠에도 담는다. 실측(2026-08-11):
      header : '(주)더스틴홀딩스대부중개' / '대부중개업 등록번호 2026-대구중구-0002'
      band[0]: '상호 (주)더스틴홀딩스대부중개'          ← 앞의 것을 그대로 포함
      band[1]: '대부중개업 등록번호 2026-대구중구-0002'  ← 완전히 동일
    같은 이미지에 두 번 찍히면서 띠만 두 줄(약 132px) 길어졌다. 정보는
    header 가 이미 갖고 있으므로 광고에서 사라지는 항목은 없다.

    ⚠ config.mandatory_lines() 와 mandatory_fingerprint() 는 **건드리지 않는다**.
      지문은 '의무표기 값이 바뀌었는가'를 보는 장치이지 배치를 보는 게 아니다.
      lines() 쪽을 줄이면 지문이 바뀌고, 이미 만들어 둔 소재가 전부
      '이미지가 현재 값과 다르다'(_profile_gate C)로 발행 차단된다.

    ⚠ 별도 함수인 이유 — 테스트가 '띠에 무엇이 그려지는가'를 확인하려면 같은
      규칙이 필요하다. 규칙을 두 곳에 적으면 한쪽만 고쳐져 조용히 어긋난다.
    """
    lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
    hdr = [_norm_line(h) for h in (header or []) if _norm_line(h)]
    if not hdr:
        return lines
    return [ln for ln in lines
            if not any(h in _norm_line(ln) or _norm_line(ln) in h for h in hdr)]


def stamp_mandatory_band(img: Image.Image, lines: list,
                         header: list = None,
                         max_glyph_ratio: float = None) -> Image.Image:
    """전단 **위·아래에** 법정 필수기재 층을 덧붙인다. 새 이미지를 반환.

    · header : [별표1] 1.가 가 요구하는 '광고 왼쪽상단'의 상호·등록번호.
               원본 위에 덮으면 헤드라인이 가려지므로 캔버스를 **위로**
               늘려 그 안에 왼쪽정렬로 그린다.
    · lines  : 나머지 필수기재 전부. 아래로 늘린 띠에 그린다.

    왜 덮지 않고 늘리나:
      전단 위에 띠를 덮으면 인쇄된 내용(연락처·장점 박스)이 잘린다.
      stamp_contact_band() 와 같은 방식으로 캔버스를 늘려 원본 손실 0.

    왜 stamp_contact_band 를 재사용하지 않나:
      그 함수는 bytes 를 받고 config.DISCLAIMER 를 직접 읽으며 docs 업종
      13개가 공유한다. 거기에 대출 의무표기를 넣으면 타 업종 광고에 대출
      문구가 붙는다. 그리고 그 함수는 상호 30px vs 의무표기 21px 로 [별표1]
      글자크기 요건 자체를 위반한다.

    글자크기: 머리글·띠 안의 모든 글자를 같은 크기(mandatory_font_px)로
      그린다. 두 법정 기준 중 엄격한 쪽을 만족한다(상수 주석 참조).
    """
    lines = [str(x).strip() for x in (lines or []) if str(x).strip()]
    header = [str(x).strip() for x in (header or []) if str(x).strip()]
    if not lines and not header:
        return img                      # 의무표기 없는 업종 - 원본 그대로

    lines = band_lines(lines, header)

    base = img.convert("RGB")
    W, H0 = base.size
    pad = int(W * 0.045)
    size = mandatory_font_px(W, max_glyph_ratio)
    font = _font_strict(size, bold=True)

    # 폭을 넘는 줄은 접는다. _wrap 은 한글을 글자 단위로 접으므로 안전하다.
    probe = ImageDraw.Draw(base)

    def _fold(src):
        out = []
        for ln in src:
            # ⚠ 맑은 고딕에 없는 글자는 두부로 찍힌다. 법정 문구에서 두부는
            #   미표기와 같으므로 **터뜨린다**(조용히 지우지 않는다).
            out.extend(_wrap(probe, _drawable_strict(ln, font), font, W - pad * 2))
        return out

    head = _fold(header)
    wrapped = _fold(lines)

    line_h = int(size * 1.45)
    head_h = (line_h * len(head) + pad) if head else 0
    band_h = (line_h * len(wrapped) + pad) if wrapped else 0

    # 밝은 바탕 + 진한 글씨. 색은 전단에서 뽑는다(band_colors).
    bg, ink, rule = band_colors(base)
    out = Image.new("RGB", (W, H0 + head_h + band_h), bg)
    out.paste(base, (0, head_h))
    draw = ImageDraw.Draw(out, "RGBA")

    def _rows(items, y):
        for ln in items:
            # x=pad 고정 = 왼쪽정렬. header 는 이미지 최상단이므로 '왼쪽상단'.
            draw.text((pad, y), ln, font=font, fill=ink)
            y += line_h
        return y

    # 전단과 띠의 경계를 눈에 보이게 긋는다. 바탕이 밝아지면서 전단의 흰
    # 여백과 붙어 보일 수 있는데, [별표1] 은 의무표기가 '그 밖의 광고사항과
    # 쉽게 구별되게' 표시될 것을 요구한다. 선이 그 경계를 대신한다.
    rule_h = max(2, int(W * BAND_RULE_RATIO))
    if head:
        _rows(head, int(pad * 0.5))
        draw.rectangle([0, head_h - rule_h, W, head_h], fill=rule)
    if wrapped:
        top = H0 + head_h
        draw.rectangle([0, top, W, top + rule_h], fill=rule)
        _rows(wrapped, top + rule_h + int(pad * 0.5))
    return out


class MandatoryIncomplete(RuntimeError):
    """의무표기 항목이 다 채워지지 않았는데 소재를 구우려 했다."""


def render_from_template(product_key: str, channel: str = "band",
                         promo: str = None, max_w: int = 1080,
                         out_path: str = None,
                         disclosures: list = None,
                         profile_key: str = None) -> str:
    """
    기존 전단지를 재사용해 채널용 크리에이티브 생성 (기본 경로·컴플라이언스 안전).
    · 이미지는 프로 디자인 그대로 — 비율 보존 리사이즈만(크롭/왜곡 없음)
    · facebook 은 배너 시트가 있으면 우선, 없으면 세로 전단 사용(개별 배너 슬라이싱은 P2)
    · promo 주면 상단 리본만 오버레이(선택)
    · 업종이 법정 필수기재사항을 선언했으면(대출 등) 하단에 의무표기 띠를 덧붙인다
    반환: 저장된 PNG 경로

    disclosures: 의무표기 줄 목록. None 이면 업종 프로필에서 가져온다.
      ⚠ 선언하지 않은 업종은 빈 목록 → 띠 없음 → 기존 동작 그대로.
        전단 JPG 원본은 절대 덮어쓰지 않는다(15장이 전 재고다).
    profile_key: 소재의 업종. None 이면 활성 프로필(config.PROFILE_KEY).

    ★ 의무표기를 선언한 업종인데 항목이 하나라도 비면 **소재를 굽지 않고
      MandatoryIncomplete 를 던진다.** 이유 - disclosure.lines() 는 빈 항목의
      줄을 조용히 빼므로, 그대로 구우면 '항목이 몇 개 빠진 띠'가 이미지에
      영구히 박힌다. 나중에 프로필을 채워 게이트가 열려도 그 이미지는
      옛날 그대로다(발행 게이트는 프로필만 보고 이미지를 보지 않았다).
    """
    tpl = registry.get(product_key)
    src = tpl.get("flyer")
    if not src:
        raise FileNotFoundError(
            f"{product_key}: JPG 렌더 없음(PSD 전용). PSD 텍스트편집(P2) 필요.")

    img = Image.open(src).convert("RGB")
    if img.width > max_w:
        nh = int(img.height * max_w / img.width)
        img = img.resize((max_w, nh), Image.LANCZOS)

    if promo:
        _overlay_promo(img, promo)

    # ★ 의무표기 - 리사이즈 **후**에 찍는다(글자크기를 최종 폭 기준으로 잡기 위해).
    #   전단 하단에 이미 인쇄된 면책문구(config.DISCLAIMER 와 사실상 동일)는
    #   여기서 다시 찍지 않는다 - 이중 표기가 된다.
    pkey = profile_key or config.PROFILE_KEY
    header = None
    if disclosures is None:
        # ★ 운영 경로는 이 분기다(orchestrator 는 disclosures 를 안 넘긴다).
        #   여기서 미완성 상태를 통과시키면 반쪽짜리 띠가 이미지에 박힌다.
        _gaps = config.compliance_gaps(pkey)
        if _gaps:
            raise MandatoryIncomplete(
                f"{pkey}: 법정 필수기재사항 미설정 - " + ", ".join(_gaps))
        lines = config.mandatory_lines(pkey)
        header = config.mandatory_header_lines(pkey)
    else:
        lines = list(disclosures)
    if lines or header:
        img = stamp_mandatory_band(img, lines, header=header)

    out = Path(out_path) if out_path else (
        config.CREATIVES_DIR / f"tpl_{product_key}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"[pamphlet] 템플릿 크리에이티브: {out} ({img.width}x{img.height}) ← {Path(src).name}")
    return str(out)
