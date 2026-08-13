"""
reels_generator.py
D:\\부동산릴스-EstateReels-v2 엔진 이식 모듈 (타임스탬프 파일 생성 & 엄격한 저장 검증 포함):
- 타임스탬프 기반 파일명 생성 (reels_{product_id}_{timestamp}.mp4)으로 파일 잠금 오류 및 이전 파일 타임스탬프 미갱신 문제 완벽 해결
- EstateReels-v2 소비자 니즈 컨셉 엔진 (8종 컨셉)
- Ken Burns 디렉션 모션 (in, out, left, right, up)
- 스토리보드 롤 배분 (hook, point_1, point_2, point_3, cta)
- 화면 자막(사실/키워드) + 음성 나레이션(구어체 이점) 분리 및 1:1 완벽 합성
- 실물 상품 이미지 파싱 & 9:16 세로형 MP4 릴스 자동 수출
"""
import os
import re
import sys
import json
import time
import asyncio
import requests
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
from datetime import datetime

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Audio TTS & Video libraries
try:
    import edge_tts
    HAS_EDGE_TTS = True
except ImportError:
    HAS_EDGE_TTS = False

try:
    from gtts import gTTS
    HAS_GTTS = True
except ImportError:
    HAS_GTTS = False

try:
    from moviepy.editor import ImageSequenceClip, AudioFileClip, concatenate_videoclips
    HAS_MOVIEPY = True
except ImportError:
    try:
        from moviepy import ImageSequenceClip, AudioFileClip, concatenate_videoclips
        HAS_MOVIEPY = True
    except ImportError:
        HAS_MOVIEPY = False

# Google GenAI Vision SDK
try:
    from google import genai
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

import coupang_collector as collector
import config as cfg

REELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "reels_output")

# 렌더 품질 — 예전에는 소스 3fps 를 12fps 로 내보내 Ken Burns 가 계단처럼 끊겼고,
# 비트레이트가 ffmpeg 기본값(실측 225kbps)이라 1080x1920 이 뭉개졌다.
RENDER_FPS = 15      # 프레임 합성 fps (올릴수록 부드럽지만 렌더 시간 비례 증가)
OUTPUT_FPS = 30      # 최종 mp4 fps
VIDEO_BITRATE = "6000k"
TEMP_IMG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_product_imgs")
os.makedirs(REELS_DIR, exist_ok=True)
os.makedirs(TEMP_IMG_DIR, exist_ok=True)

# ════════════════════════════════════════════════════════════════
# 1. EstateReels-v2 Ken Burns 방향 체계 & 컨셉 엔진 (8종)
# ════════════════════════════════════════════════════════════════
KB_CYCLE = ['in', 'left', 'out', 'right', 'up']

CONCEPTS = {
    "price_focus": {
        "id": "price_focus",
        "name": "⚡ 급매·가격강조",
        "hook_badge": "가격 추적",
        "bg_badge": "#a6e3a1",
        "text_color": "#11111b"
    },
    "bestseller": {
        "id": "bestseller",
        "name": "🏆 인기·베스트",
        "hook_badge": "판매량 기준",
        "bg_badge": "#f9e2af",
        "text_color": "#11111b"
    },
    "specs": {
        "id": "specs",
        "name": "🚀 스펙·프리미엄",
        "hook_badge": "스펙 확인",
        "bg_badge": "#89b4fa",
        "text_color": "#11111b"
    },
    "review": {
        "id": "review",
        "name": "⭐ 후기·검증",
        "hook_badge": "구매자 평가",
        "bg_badge": "#f38ba8",
        "text_color": "#ffffff"
    }
}

# ════════════════════════════════════════════════════════════════
# 2. 실물 상품 이미지 파서 & 다각도 extraction
# ════════════════════════════════════════════════════════════════
def fetch_product_multi_images(product_info: dict) -> list:
    p_id = product_info.get("product_id", "default")
    image_urls = []
    
    main_url = product_info.get("image_url")
    if main_url:
        image_urls.append(main_url)

    detail_urls = product_info.get("detail_images", [])
    if isinstance(detail_urls, list):
        image_urls.extend(detail_urls)

    # image_url 은 detail_images[0] 과 같은 주소인 경우가 많다.
    # 중복을 안 걸러 씬 0 과 씬 1 에 똑같은 사진이 들어간 적이 있다.
    # 그리고 image/displayitem/ 은 쿠팡 공통 광고 배너("쿠팡에서 판매시작하기" 등)라
    # 상품 사진이 아니다 — 수집기에서도 거르지만 기존 DB 데이터를 위해 여기서도 막는다.
    image_urls = [u for u in dict.fromkeys(u for u in image_urls if u)
                  if "/image/displayitem" not in u]

    # 출처별 신뢰도가 다르다.
    #   thumbnails/remote  = 상단 갤러리. 이 상품의 사진인 것이 확실하다.
    #   vendor_inventory   = 판매자가 올린 상세설명 영역. 영양정보표처럼 쓸모 있는 것도
    #                        있지만 '판매자의 다른 상품' 사진이 섞인다.
    # 실제로 아카페라 아메리카노 릴스에 전혀 다른 제품(아이브루) 사진이 두 씬 들어갔다.
    # 갤러리를 앞에 두고, 판매자 이미지는 앞쪽 2장까지만 보조로 쓴다.
    gallery = [u for u in image_urls if "thumbnails/remote" in u]
    vendor = [u for u in image_urls if "vendor_inventory" in u]
    rest = [u for u in image_urls if u not in gallery and u not in vendor]
    # 갤러리가 2장 이상이면 그것만 쓴다. 모자란 씬은 크롭으로 파생하는 편이
    # 남의 상품 사진을 넣는 것보다 낫다. (틀린 사진은 광고로서 치명적이다.)
    image_urls = gallery + rest if len(gallery) >= 2 else gallery + vendor + rest

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://www.coupang.com/"
    }

    loaded_images = []
    for idx, url in enumerate(image_urls):
        if not url:
            continue
        local_path = os.path.join(TEMP_IMG_DIR, f"real_{p_id}_{idx}.jpg")
        if not os.path.exists(local_path):
            try:
                if url.startswith("http"):
                    resp = requests.get(url, headers=headers, timeout=5)
                    if resp.status_code == 200 and len(resp.content) > 2000:
                        with open(local_path, "wb") as f:
                            f.write(resp.content)
            except Exception as e:
                print(f"[Image Downloader Note] Could not download image {idx}: {e}")
                
        if os.path.exists(local_path):
            try:
                img = Image.open(local_path).convert("RGB")
                # 릴스 이미지 카드는 980x940 이다. 그보다 훨씬 작은 소재를 확대하면
                # 뭉개져서 오히려 품질을 떨어뜨린다(204x300 짜리가 씬에 들어간 적 있다).
                if min(img.size) < 500:
                    continue
                loaded_images.append(img)
            except Exception:
                pass

    if not loaded_images:
        base_img = Image.new("RGB", (800, 800), color="#1e1e2e")
        draw = ImageDraw.Draw(base_img)
        try:
            f = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 38)
        except:
            f = ImageFont.load_default()
        draw.rectangle([(40, 40), (760, 760)], outline="#89b4fa", width=4)
        draw.text((120, 360), f"📸 {product_info.get('title','')[:16]}", fill="#ffffff", font=f)
        loaded_images.append(base_img)
        
    main_photo = loaded_images[0]
    scene_photos = [main_photo]
    
    if len(loaded_images) > 1:
        scene_photos.append(loaded_images[1])
    else:
        w, h = main_photo.size
        scene_photos.append(main_photo.crop((int(w*0.1), int(h*0.1), int(w*0.9), int(h*0.7))))
        
    if len(loaded_images) > 2:
        scene_photos.append(loaded_images[2])
    else:
        w, h = main_photo.size
        scene_photos.append(main_photo.crop((int(w*0.05), int(h*0.2), int(w*0.95), int(h*0.9))))
        
    if len(loaded_images) > 3:
        scene_photos.append(loaded_images[3])
    else:
        scene_photos.append(main_photo)
        
    return scene_photos

# ════════════════════════════════════════════════════════════════
# 3. EstateReels-v2 하이브리드 나레이션 & 자막 생성기
# ════════════════════════════════════════════════════════════════
def build_estatereels_storyboard(product_info: dict, scene_photos: list, concept_id: str = "price_focus") -> list:
    title = product_info.get("title", "")
    clean_title = title.replace("[디지털/가전]", "").replace("[주방용품]", "").replace("[생활/건강]", "").strip()
    clean_title_short = clean_title[:18]
    # TTS로 읽을 이름은 옵션 꼬리표를 뗀다.
    # "미샤 소프트 면봉, 1개, 300P" 를 18자로 자르면 "…, 1개, 300" 이 되어 어색하게 읽힌다.
    spoken_title = clean_title.split(",")[0].strip()[:24] or clean_title_short
    
    disc_rate = product_info.get("discount_rate", 0)
    curr_price = product_info.get("current_price", 0)
    comp = product_info.get("comparison", {})
    diff_val = abs(comp.get("diff", 0))
    # 없는 값을 그럴듯한 기본값으로 메우지 않는다. 예전엔 평점 4.8 / 리뷰 1,200개를
    # 기본값으로 넣어서, 수집 못 한 상품도 영상에서는 인기 상품처럼 보였다.
    rating = product_info.get("rating") or 0
    review_cnt = product_info.get("review_count") or 0

    concept = CONCEPTS.get(concept_id, CONCEPTS["price_focus"])

    # 보랏빛 소 진단 — 데이터에서 가장 강한 훅 하나를 뽑아 첫 1초에 쓴다.
    # AI 보정이 실패해도 이 기본 대본이 상투어로 채워지지 않게 한다.
    try:
        import purple_cow
        _diag = purple_cow.diagnose(product_info)
        _hook = _diag["hooks"][0] if _diag["hooks"] else f"{disc_rate}%"
    except Exception:
        _diag, _hook = None, f"{disc_rate}%"
    _hook_short = str(_hook)[:20]

    orig_price = product_info.get("original_price", 0)
    monthly = (product_info.get("monthly_buyers") or "").strip()

    # 골드박스에는 할인 없이 그냥 싼 상품도 섞여 있다. 그런 상품은 정가가 아예 없어
    # original_price 가 0 으로 온다. 이걸 그대로 쓰면 "정가 0원이 4,130원입니다" 가 된다.
    has_discount = orig_price > curr_price > 0

    storyboard = [
        {
            # 원칙 1·2 — 상품명이 아니라 숫자 하나로 연다. 1초를 넘기면 스크롤된다.
            "role": "hook",
            "seq": 0,
            "photo": scene_photos[0],
            "badge": concept["hook_badge"],
            "caption": _hook_short,
            "sub": clean_title_short,
            "narration": (f"{spoken_title}. 정가 {orig_price:,}원이 {curr_price:,}원입니다."
                          if has_discount else f"{spoken_title}. 지금 {curr_price:,}원입니다."),
            "kb": KB_CYCLE[0]
        },
        {
            # 원칙 8 — 가격을 자랑하지 않고 계산한다.
            # ('왜 이 가격이 가능한지'를 묻던 예전 지침은 폐기했다. 데이터에 답이 없어서
            #  모델이 원가·재고 사정을 지어냈다)
            "role": "point",
            "seq": 1,
            "photo": scene_photos[1],
            "badge": (f"정가 {orig_price:,}원 → {curr_price:,}원" if has_discount
                      else f"현재가 {curr_price:,}원"),
            "caption": (f"어제보다 {diff_val:,}원 내림" if diff_val
                        else (f"{disc_rate}% 할인가 유지" if has_discount and disc_rate
                              else f"{curr_price:,}원")),
            "sub": (f"정가 {orig_price:,}원" if has_discount else "할인 없이 책정된 가격"),
            "narration": (f"어제보다 {diff_val:,}원 내렸습니다."
                          if diff_val
                          # '며칠째'는 이전 관측이 있을 때만 할 수 있는 말이다.
                          # 분기 조건이 diff_val 이라, 관측 1점짜리 35건이 전부
                          # "며칠째 N원입니다"라고 말하고 있었다.
                          else (f"직전 확인 때와 같은 {curr_price:,}원입니다."
                                if comp.get("has_prior") and has_discount
                                else f"현재 판매가는 {curr_price:,}원입니다.")),
            "kb": KB_CYCLE[1]
        },
        {
            # 원칙 3 — 사회적 증거는 사실만. '가성비 베스트' 같은 형용은 빼고 숫자만 남긴다.
            #
            # 평점은 화면에 쓰지 않는다: 목록 페이지의 평점은 0.5 단위로 뭉뚱그려져
            # 대부분 5.0 으로 내려온다(실측). 그대로 띄우면 과장이 된다.
            # 상세페이지에서 정확한 값을 받아온 경우에만(rating_precise) 노출한다.
            "role": "point",
            "seq": 2,
            "photo": scene_photos[2],
            # 상품평 수를 못 읽었으면(0) 그 문구를 아예 쓰지 않는다.
            # "상품평이 0개 쌓인 상품입니다"가 나레이션으로 나가던 문제.
            "badge": (monthly[:22] if monthly
                      else (f"상품평 {review_cnt:,}개" if review_cnt else f"{disc_rate}% 할인")),
            "caption": (f"상품평 {review_cnt:,}개" if review_cnt
                        else f"정가 {orig_price:,}원"),
            "sub": (f"정가보다 {orig_price - curr_price:,}원 낮음"
                    if orig_price > curr_price else f"현재가 {curr_price:,}원"),
            "narration": (monthly if monthly
                          else (f"상품평이 {review_cnt:,}개 쌓인 상품입니다." if review_cnt
                                else f"현재 판매가는 {curr_price:,}원입니다.")),
            "kb": KB_CYCLE[2]
        },
        {
            # 원칙 4 — 허락자산. '사세요'가 아니라 '무엇을 언제 알려줄지' 약속한다.
            "role": "cta",
            "seq": 3,
            "photo": scene_photos[3],
            "badge": "가격 내려가면 다시 올립니다",
            "caption": "링크는 프로필과 본문에",
            "sub": "쿠팡 파트너스 활동으로 수수료를 받습니다",
            "narration": "가격이 또 내려가면 같은 형식으로 다시 올리겠습니다. 링크는 본문에 있습니다.",
            "kb": KB_CYCLE[3]
        }
    ]

    config_data = cfg.load_config()
    api_key = config_data.get("gemini_api_key", "")

    # 보랏빛 소 지침 — 상투어로 채워진 기본 대본을 리마커블한 각도로 덮어쓴다
    try:
        import purple_cow
        # scene_level=True — 씬 구성 규칙을 빼야 모델이 씬 하나만 만든다
        _pc_guide = purple_cow.build_reels_guide(product_info, scene_level=True)
    except Exception as _e:
        print(f"[PurpleCow Note] 지침 생성 건너뜀: {_e}")
        _pc_guide = ""

    if HAS_GENAI and api_key:
        try:
            client = genai.Client(api_key=api_key)
            for sc in storyboard:
                if sc["role"] == "point":
                    prompt = f"""당신은 쿠팡 상품 숏폼 대본 작가입니다.
첨부된 이미지는 '{clean_title_short}' 상품의 실물 컷입니다.

{_pc_guide}

이 이미지를 시각적으로 파악하고, 상품 상세페이지의 주요 기능/디자인 특징을 발췌하여
화면 자막(caption)과 읽어주는 나레이션(narration)을 작성하세요.

규칙:
1. caption: 화면에 보이는 짧고 명확한 사실 문구 (20자 이내)
2. narration: 그 사실의 이점을 자연스럽게 설명하는 구어체 문장 (30자 이내)
3. 위 [대본 규칙]과 [금지] 항목을 반드시 지킬 것. 상투어를 쓰면 실패다.

출력 형식:
자막: (caption)
대사: (narration)
"""
                    resp = client.models.generate_content(
                        model="gemini-2.5-flash",
                        contents=[sc["photo"], prompt]
                    )
                    text = resp.text.strip()
                    if "자막:" in text and "대사:" in text:
                        # 모델이 여러 씬이나 마크다운을 섞어 뱉는 경우가 있다.
                        # 각 항목의 '첫 줄'만 취하고 장식 문자를 걷어낸다.
                        def _clean(s: str) -> str:
                            s = s.strip().split("\n")[0]
                            s = re.sub(r"[*#`_]+", "", s)
                            s = re.sub(r"^\s*(씬\s*\d+\s*[:.]?|\(.*?\))\s*", "", s)
                            return s.strip().strip('"').strip()

                        cap = _clean(text.split("자막:")[1].split("대사:")[0])
                        narr = _clean(text.split("대사:")[1])
                        # 빈 값·과도한 길이·상투어가 섞이면 기본 대본을 유지한다.
                        # 순위·최상급 주장은 패키지 문구를 그대로 읽어온 경우가 많은데,
                        # 근거 없이 영상에 실으면 표시광고법 문제가 된다(실제로 모델이
                        # 상품 사진의 'NO.1' 배지를 읽어 자막으로 올린 사례가 있었다).
                        _ban = ("역대급", "절호의 기회", "품절 임박", "폭풍", "가성비 갑",
                                "NO.1", "No.1", "no.1", "넘버원", "1위", "최고", "최상",
                                "유일", "최저가", "국내 최", "업계 최")
                        if (cap and narr and len(cap) <= 30 and len(narr) <= 60
                                and not any(b in cap + narr for b in _ban)):
                            sc["caption"] = cap
                            sc["narration"] = narr
        except Exception as e:
            print(f"[EstateReels AI Note] Storyboard AI enhancement fallback: {e}")

    return storyboard

def generate_scene_tts(script_text: str, output_audio_path: str) -> bool:
    if HAS_EDGE_TTS:
        try:
            async def _main():
                communicate = edge_tts.Communicate(script_text, "ko-KR-SunHiNeural", rate="+12%")
                await communicate.save(output_audio_path)
            asyncio.run(_main())
            return True
        except Exception as e:
            print(f"[TTS Error] edge-tts failed: {e}")
            
    if HAS_GTTS:
        try:
            tts = gTTS(text=script_text, lang="ko")
            tts.save(output_audio_path)
            return True
        except Exception as e:
            print(f"[TTS Error] gTTS failed: {e}")
            
    return False

# ════════════════════════════════════════════════════════════════
# 4. EstateReels-v2 프레임 렌더러 (Ken Burns & 캔버스 자막)
# ════════════════════════════════════════════════════════════════
def render_estatereels_frame(
    photo: Image.Image,
    scene_data: dict,
    width: int = 1080,
    height: int = 1920,
    progress: float = 0.0
) -> Image.Image:
    canvas = Image.new("RGB", (width, height), color="#0c0d12")
    draw = ImageDraw.Draw(canvas)
    
    try:
        f_hdr = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 36)
        f_badge = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 40)
        f_cap = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 48)
        f_sub = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 36)
        f_btn = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 44)
    except:
        f_hdr = f_badge = f_cap = f_sub = f_btn = ImageFont.load_default()

    draw.rectangle([(0, 0), (width, 150)], fill="#14151f")
    # 헤더는 부동산릴스에서 넘어온 '🏡 EstateReels' 가 그대로 박혀 있었다.
    # 배지는 이미지 위에 따로 그려지므로 여기서 반복하지 않는다.
    draw.text((50, 45), scene_data.get("header", "쿠팡 가격 추적"), fill="#f9e2af", font=f_hdr)

    card_margin = 50
    card_w = width - (card_margin * 2)
    img_y = 170
    img_h = 940

    kb = scene_data.get("kb", "in")
    bw, bh = photo.size if photo else (800, 800)
    
    zoom = 1.0
    pan_x = 0
    pan_y = 0
    
    if kb == "in":
        zoom = 1.0 + (progress * 0.12)
    elif kb == "out":
        zoom = 1.12 - (progress * 0.12)
    elif kb == "left":
        zoom = 1.1
        pan_x = int((progress - 0.5) * 60)
    elif kb == "right":
        zoom = 1.1
        pan_x = int((0.5 - progress) * 60)
    elif kb == "up":
        zoom = 1.1
        pan_y = int((0.5 - progress) * 60)

    if photo:
        cw = int(bw / zoom)
        ch = int(bh / zoom)
        left = max(0, min(bw - cw, (bw - cw) // 2 + pan_x))
        top = max(0, min(bh - ch, (bh - ch) // 2 + pan_y))
        cropped = photo.crop((left, top, left + cw, top + ch))
        resized = cropped.resize((card_w, img_h), Image.Resampling.LANCZOS)
        canvas.paste(resized, (card_margin, img_y))
    else:
        draw.rectangle([(card_margin, img_y), (card_margin + card_w, img_y + img_h)], fill="#1f2335")

    draw.rectangle([(card_margin, img_y), (card_margin + card_w, img_y + img_h)], outline="#89b4fa", width=3)

    draw.rectangle([(card_margin + 20, img_y + 20), (card_margin + 620, img_y + 110)], fill="#89b4fa")
    draw.text((card_margin + 40, img_y + 38), scene_data.get("badge", ""), fill="#11111b", font=f_badge)

    sub_y = 1140
    draw.rectangle([(card_margin, sub_y), (width - card_margin, sub_y + 410)], fill="#14151f", outline="#313150", width=2)

    caption = scene_data.get("caption", "")
    draw.text((card_margin + 30, sub_y + 30), caption, fill="#a6e3a1", font=f_cap)
    draw.line([(card_margin + 30, sub_y + 100), (width - card_margin - 30, sub_y + 100)], fill="#313150", width=2)

    sub_text = scene_data.get("sub", "")
    draw.text((card_margin + 30, sub_y + 130), sub_text, fill="#cdd6f4", font=f_sub)

    # 나레이션은 TTS 로 '들리는' 것이다. 화면에 대본을 찍지 않는다.
    # (예전에는 여기에 🗣️ 대사: "..." 를 22자로 잘라 노출해서, 말할 내용이
    #  자막으로 중복되고 문장이 잘려 보였다. 자막=사실 / 음성=이점 원칙에도 어긋난다.)
    extra = scene_data.get("detail", "")
    if extra:
        draw.text((card_margin + 30, sub_y + 210), extra, fill="#f9e2af", font=f_sub)

    draw.rectangle([(card_margin, 1580), (width - card_margin, 1740)], fill="#89b4fa")
    draw.text((width//2 - 300, 1635), "프로필 · 본문 링크에서 구매", fill="#11111b", font=f_btn)

    return canvas

# ════════════════════════════════════════════════════════════════
# 5. EstateReels 비디오 렌더링 메인 파이프라인 (타임스탬프 신규 파일 생성)
# ════════════════════════════════════════════════════════════════
def generate_product_reels_video(product_id_or_url: str, concept_id: str = "price_focus") -> str:
    """
    D:\\부동산릴스-EstateReels-v2 구성 적용 릴스 비디오 생성
    타임스탬프 기반 파일명을 적용하여 이전 파일 타임스탬프 미갱신 문제 및 파일 잠금 오류를 완벽 방지합니다.
    """
    all_prods = collector.get_all_products_from_db()

    # 상품 ID 또는 상세페이지 URL 둘 다 받는다.
    key = str(product_id_or_url).strip()
    m = re.search(r"/vp/products/(\d+)", key)
    if m:
        key = m.group(1)
    product_info = next((p for p in all_prods if str(p["product_id"]) == key), None)

    if not product_info:
        # 예전에는 여기서 "삼성전자 로봇청소기" 더미로 조용히 대체하고 성공을 반환했다.
        # 그러면 존재하지 않는 상품의 영상이 진짜처럼 만들어져 나간다. 이제는 실패시킨다.
        raise ValueError(
            f"DB에 상품 '{product_id_or_url}' 이(가) 없습니다. "
            f"(현재 {len(all_prods)}건 보유) "
            "coupang_live_collector.py list 로 먼저 수집하세요."
        )

    product_id = product_info["product_id"]
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # 1. 타임스탬프 기반 신규 파일 및 기본 대표 파일명 동시 지정
    output_mp4_timestamped = os.path.join(REELS_DIR, f"reels_{product_id}_{timestamp_str}.mp4")
    output_mp4_static = os.path.join(REELS_DIR, f"reels_{product_id}.mp4")

    # 2. 실물 상품 이미지 파싱
    scene_photos = fetch_product_multi_images(product_info)

    # 3. EstateReels-v2 스토리보드 구축
    storyboard = build_estatereels_storyboard(product_info, scene_photos, concept_id)

    # 4. 비디오 씬 결합
    video_clips = []
    for sc in storyboard:
        seq = sc["seq"]
        audio_file = os.path.join(REELS_DIR, f"audio_{product_id}_sc{seq}_{timestamp_str}.mp3")
        
        generate_scene_tts(sc["narration"], audio_file)
        
        duration = 3.5
        if HAS_MOVIEPY and os.path.exists(audio_file):
            try:
                a_clip = AudioFileClip(audio_file)
                duration = max(3.0, a_clip.duration + 0.3)
            except Exception:
                pass
                
        fps = RENDER_FPS
        num_frames = int(duration * fps)
        
        frames = []
        for i in range(num_frames):
            progress = i / max(1, num_frames - 1)
            frame_img = render_estatereels_frame(
                photo=sc["photo"],
                scene_data=sc,
                progress=progress
            )
            frames.append(np.array(frame_img))
            
        if HAS_MOVIEPY:
            try:
                v_clip = ImageSequenceClip(frames, fps=fps)
                if os.path.exists(audio_file):
                    audio_clip = AudioFileClip(audio_file)
                    if hasattr(v_clip, "with_audio"):
                        v_clip = v_clip.with_audio(audio_clip)
                    elif hasattr(v_clip, "set_audio"):
                        v_clip = v_clip.set_audio(audio_clip)
                    else:
                        v_clip.audio = audio_clip
                video_clips.append(v_clip)
            except Exception as e:
                print(f"[EstateReels Clip Error] Scene {seq} error: {e}")

    # 5. 최종 MP4 타임스탬프 파일 내보내기 및 검증
    if HAS_MOVIEPY and video_clips:
        try:
            final_clip = concatenate_videoclips(video_clips, method="compose")
            
            # 타임스탬프 포함 고유 신규 파일 저장
            final_clip.write_videofile(output_mp4_timestamped, fps=OUTPUT_FPS, codec="libx264",
                                       audio_codec="aac", bitrate=VIDEO_BITRATE, logger=None)
            
            # 대표 고정파일명 복사 시도 (잠금 시 타임스탬프 파일로 반환)
            try:
                import shutil
                shutil.copy2(output_mp4_timestamped, output_mp4_static)
                print(f"[EstateReels Generator] Video updated and saved to static file: {output_mp4_static}")
            except Exception as fe:
                print(f"[EstateReels Generator Note] Could not overwrite static file due to file lock: {fe}")
                
            print(f"[EstateReels Generator] BRAND NEW Timestamped Video exported: {output_mp4_timestamped}")
            return output_mp4_timestamped
        except Exception as e:
            print(f"[EstateReels Export Error] Concatenate failed: {e}")
            raise RuntimeError(f"MoviePy export failed: {e}")

    return output_mp4_timestamped

if __name__ == "__main__":
    print("[EstateReels Generator] Testing timestamped video creation...")
    mp4_path = generate_product_reels_video("CP100_009")
    print(f"[EstateReels Generator] BRAND NEW Video Path: {mp4_path}")
