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


def render_from_template(product_key: str, channel: str = "band",
                         promo: str = None, max_w: int = 1080,
                         out_path: str = None) -> str:
    """
    기존 전단지를 재사용해 채널용 크리에이티브 생성 (기본 경로·컴플라이언스 안전).
    · 이미지는 프로 디자인 그대로 — 비율 보존 리사이즈만(크롭/왜곡 없음)
    · facebook 은 배너 시트가 있으면 우선, 없으면 세로 전단 사용(개별 배너 슬라이싱은 P2)
    · promo 주면 상단 리본만 오버레이(선택)
    반환: 저장된 PNG 경로
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

    out = Path(out_path) if out_path else (
        config.CREATIVES_DIR / f"tpl_{product_key}_{channel}.png")
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, "PNG")
    print(f"[pamphlet] 템플릿 크리에이티브: {out} ({img.width}x{img.height}) ← {Path(src).name}")
    return str(out)
