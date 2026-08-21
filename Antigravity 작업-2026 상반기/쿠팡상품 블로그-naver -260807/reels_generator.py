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

    # detail_images 는 DB 에 JSON 문자열로 들어 있다.
    # collector.get_all_products_from_db() 는 파싱해서 주지만, DB 를 직접 조회한
    # 쪽(video_pipeline.pick_targets 등)은 문자열 그대로 넘긴다. 예전에는 리스트가
    # 아니면 조용히 버려서, 사진이 여러 장 있어도 대표 이미지 1장만 쓰였다.
    detail_urls = product_info.get("detail_images") or []
    if isinstance(detail_urls, str):
        try:
            detail_urls = json.loads(detail_urls)
        except Exception:
            detail_urls = []
    if isinstance(detail_urls, list):
        image_urls.extend(detail_urls)

    # 갤러리 썸네일이 따로 저장되는 상품이 있다(수집기의 thumbnails 컬럼).
    # 이걸 안 읽어서 쓸 수 있는 사진을 놓치고 있었다.
    thumbs = product_info.get("thumbnails") or []
    if isinstance(thumbs, str):
        try:
            thumbs = json.loads(thumbs)
        except Exception:
            thumbs = []
    if isinstance(thumbs, list):
        image_urls.extend(thumbs)

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
        
    # 상품 사진이 모자라면 상품평 사진으로 채운다.
    #
    # 예전에는 무조건 4장을 맞추느라 대표 이미지를 잘라 쓰거나 그대로 한 번 더
    # 넣었다. 그러면 같은 병 사진이 네 장면에 계속 나온다. 재탕은 하지 않는다.
    # 상품평 사진은 구매자가 찍은 것이라 얼굴·문서가 섞여 있다 — review_photos 가
    # 그것들을 걸러 낸다. 자세한 사정은 그 모듈 설명에 적어 두었다.
    if len(loaded_images) < 4:
        try:
            import review_photos
            extra = review_photos.usable_review_photos(
                product_info, want=4 - len(loaded_images))
            loaded_images.extend(extra)
        except Exception as e:
            print(f"[Review Photo Note] 상품평 사진을 쓰지 못했습니다: {str(e)[:90]}")

    # 그래도 모자라면 있는 만큼만 쓴다. 장면 수를 사진 수에 맞춘다.
    return loaded_images[:4]


def count_product_images(product_info: dict) -> int:
    """이 상품으로 만들 수 있는 장면 수. 대사 길이를 여기에 맞춘다."""
    return max(1, len(fetch_product_multi_images(product_info)))

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

    # 여기서 말하는 '정가'는 판매자가 상세페이지에 적어 둔 값이지, 시장에서 확인된
    # 값이 아니다. 실제로 1L 아메리카노 12개 묶음의 정가가 167,700원(개당 13,975원)
    # 으로 적힌 상품이 있었다 — 89% 할인이 된다. 이런 부풀린 정가를 우리가 보증하듯
    # "정가보다 149,620원 낮음"이라고 쓰면 표시광고법 문제가 우리 쪽으로 넘어온다.
    # 그래서 정가를 말할 때는 반드시 출처를 붙인다.
    ORIG_LABEL = "쿠팡 표시 정가"

    storyboard = [
        {
            # 원칙 1·2 — 상품명이 아니라 숫자 하나로 연다. 1초를 넘기면 스크롤된다.
            "role": "hook",
            "seq": 0,
            "photo": scene_photos[0] if len(scene_photos) > 0 else None,
            "badge": concept["hook_badge"],
            "caption": _hook_short,
            "sub": clean_title_short,
            "narration": (f"{spoken_title}. {ORIG_LABEL} {orig_price:,}원이 {curr_price:,}원입니다."
                          if has_discount else f"{spoken_title}. 지금 {curr_price:,}원입니다."),
            "kb": KB_CYCLE[0]
        },
        {
            # 원칙 8 — 가격을 자랑하지 않고 계산한다.
            # ('왜 이 가격이 가능한지'를 묻던 예전 지침은 폐기했다. 데이터에 답이 없어서
            #  모델이 원가·재고 사정을 지어냈다)
            "role": "point",
            "seq": 1,
            "photo": scene_photos[1] if len(scene_photos) > 1 else None,
            "badge": (f"{ORIG_LABEL} {orig_price:,}원 → {curr_price:,}원" if has_discount
                      else f"현재가 {curr_price:,}원"),
            "caption": (f"어제보다 {diff_val:,}원 내림" if diff_val
                        else (f"{disc_rate}% 할인가 유지" if has_discount and disc_rate
                              else f"{curr_price:,}원")),
            "sub": (f"{ORIG_LABEL} {orig_price:,}원" if has_discount else "할인 없이 책정된 가격"),
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
            "photo": scene_photos[2] if len(scene_photos) > 2 else None,
            # 상품평 수를 못 읽었으면(0) 그 문구를 아예 쓰지 않는다.
            # "상품평이 0개 쌓인 상품입니다"가 나레이션으로 나가던 문제.
            "badge": (monthly[:22] if monthly
                      else (f"상품평 {review_cnt:,}개" if review_cnt else f"{disc_rate}% 할인")),
            "caption": (f"상품평 {review_cnt:,}개" if review_cnt
                        else f"{ORIG_LABEL} {orig_price:,}원"),
            "sub": (f"{ORIG_LABEL} 대비 {orig_price - curr_price:,}원 낮음"
                    if has_discount else f"현재가 {curr_price:,}원"),
            "narration": (monthly if monthly
                          else (f"상품평이 {review_cnt:,}개 쌓인 상품입니다." if review_cnt
                                else f"현재 판매가는 {curr_price:,}원입니다.")),
            "kb": KB_CYCLE[2]
        },
        {
            # 원칙 4 — 허락자산. '사세요'가 아니라 '무엇을 언제 알려줄지' 약속한다.
            "role": "cta",
            "seq": 3,
            "photo": scene_photos[3] if len(scene_photos) > 3 else None,
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
                    # 모델명을 여기에 박아 두면 구글이 그 버전을 내릴 때 404 로 죽는다.
                    # (실제로 gemini-2.5-flash 가 신규 사용자에게 막혀 조용히 폴백됐다)
                    # ai_writer 한 곳에서만 관리한다.
                    import ai_writer
                    resp = client.models.generate_content(
                        model=ai_writer.MODEL,
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

    # 사진이 없는 장면은 버린다. 사진이 2장이면 장면도 2개다.
    # 예전처럼 대표 이미지를 재탕해 4장면을 억지로 채우지 않는다.
    storyboard = [sc for sc in storyboard if sc.get("photo") is not None]
    if not storyboard:
        raise ValueError("쓸 수 있는 상품 이미지가 한 장도 없습니다.")

    return storyboard

def generate_scene_tts(script_text: str, output_audio_path: str, rate: str = "+12%") -> bool:
    """
    나레이션 음성을 만든다.

    rate 는 edge-tts 의 증감률 표기다. 기본 속도 대비 얼마나 빠른가를 뜻한다.
      +12%  블로그용 기본
      +50%  1.5배속 — 릴스처럼 짧게 끊어 가는 영상에 쓴다
    """
    if HAS_EDGE_TTS:
        try:
            async def _main():
                communicate = edge_tts.Communicate(script_text, "ko-KR-SunHiNeural", rate=rate)
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
def _fit_font(paths, size):
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_estatereels_frame(
    photo: Image.Image,
    scene_data: dict,
    width: int = 1080,
    height: int = 1920,
    progress: float = 0.0
) -> Image.Image:
    """
    릴스 한 프레임을 그린다.

    ## 배치 원칙
    인스타 릴스는 영상을 다 보여주지 않는다. 위는 상태바와 헤더가, 아래는 계정명·
    캡션·음원 표시가, 오른쪽은 좋아요/댓글/공유 버튼이 덮는다. 그래서 내용을
    y 210~1500, x 60~950 안에만 그린다.

    ## 예전 배치에서 고친 것
    - 상품 사진 칸이 700px 로 작아 상품이 잘 안 보였다. 880px 로 키웠다.
    - 사진을 칸 크기로 늘려 넣어 정보 이미지 글자가 잘렸다. 비율을 지켜 통째로 넣는다.
    - 파란 테두리·꽉 찬 배지·굵은 구분선이 상품보다 눈에 띄었다. 다 덜어 냈다.
    - 자막이 한 줄로 그려져 화면 밖으로 잘렸다. 어절 단위로 접는다.
    """
    BG = "#0b0c10"
    CARD = "#15171f"
    LINE = "#262a38"
    TEXT = "#f2f4f8"
    MUTED = "#9aa3b8"
    ACCENT = "#7cc4ff"
    GOLD = "#ffd479"

    BOLD = ["C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf"]
    REG = ["C:/Windows/Fonts/malgun.ttf"]
    f_head = _fit_font(BOLD, 30)
    f_badge = _fit_font(BOLD, 36)
    f_cap = _fit_font(BOLD, 56)
    f_sub = _fit_font(REG, 36)
    f_cta = _fit_font(BOLD, 44)

    canvas = Image.new("RGB", (width, height), color=BG)
    draw = ImageDraw.Draw(canvas)

    SAFE_TOP, SAFE_BOTTOM = 210, 1500
    L, R = 60, 950          # 오른쪽 버튼 세로줄을 피한다
    inner = R - L

    def wrap(text, font, max_w, max_lines):
        """어절 단위로 접는다. 한 어절이 통째로 넘치면 글자 단위로 끊는다."""
        out, cur = [], ""
        for word in (text or "").split():
            trial = (cur + " " + word).strip()
            if draw.textlength(trial, font=font) <= max_w:
                cur = trial
                continue
            if cur:
                out.append(cur)
                cur = ""
            if draw.textlength(word, font=font) <= max_w:
                cur = word
            else:
                for ch in word:
                    if draw.textlength(cur + ch, font=font) <= max_w:
                        cur += ch
                    else:
                        out.append(cur)
                        cur = ch
            if len(out) >= max_lines:
                break
        if cur and len(out) < max_lines:
            out.append(cur)
        return out[:max_lines]

    # ── 머리말 ───────────────────────────────────────────────
    head = scene_data.get("header", "쿠팡 가격 추적")
    draw.text((L, SAFE_TOP - 58), head, fill=MUTED, font=f_head)
    draw.line([(L, SAFE_TOP - 16), (R, SAFE_TOP - 16)], fill=LINE, width=2)

    # ── 상품 사진 ────────────────────────────────────────────
    img_y, img_h = SAFE_TOP + 20, 880
    draw.rectangle([(L, img_y), (R, img_y + img_h)], fill=CARD)

    if photo:
        # 움직임은 살짝 확대에서 시작해 전체가 보이는 상태로 끝난다.
        # 내내 확대해 두면 영양성분표 같은 정보 이미지의 양옆 글자가 잘린다.
        zoom = 1.05 - (progress * 0.05)
        bw, bh = photo.size
        cw, ch = int(bw / zoom), int(bh / zoom)
        left = max(0, (bw - cw) // 2)
        top = max(0, (bh - ch) // 2)
        crop = photo.crop((left, top, left + cw, top + ch))

        # 비율을 지켜 칸 안에 통째로 넣는다. 늘리면 상품이 일그러진다.
        scale = min(inner / crop.width, img_h / crop.height)
        nw, nh = max(1, int(crop.width * scale)), max(1, int(crop.height * scale))
        canvas.paste(crop.resize((nw, nh), Image.Resampling.LANCZOS),
                     (L + (inner - nw) // 2, img_y + (img_h - nh) // 2))

    # 배지 — 사진 위에 얇게 얹는다
    badge = (scene_data.get("badge") or "").strip()
    if badge:
        bw_ = draw.textlength(badge, font=f_badge)
        pad = 20
        bx, by = L + 24, img_y + 24
        draw.rectangle([(bx, by), (bx + bw_ + pad * 2, by + 62)], fill=ACCENT)
        draw.text((bx + pad, by + 12), badge, fill="#0b0c10", font=f_badge)

    # ── 자막 ─────────────────────────────────────────────────
    #
    # 글이 구매 안내 띠를 넘어가면 안 된다. 예전 배치에서 상품명 줄이 띠 위에
    # 겹쳐 찍혀 둘 다 읽을 수 없었다. 남은 높이를 보고, 자리가 없으면 그 줄을 뺀다.
    # 자막이 우선이다 — 상품명은 캡션에도 적히지만 자막은 여기밖에 없다.
    cy = SAFE_BOTTOM - 92           # 구매 안내 띠의 윗변
    limit = cy - 24                 # 글이 넘어서면 안 되는 선

    def put(text, font, fill, step, max_lines):
        nonlocal y
        for ln in wrap(text, font, inner, max_lines):
            if y + step > limit:
                return
            draw.text((L, y), ln, fill=fill, font=font)
            y += step

    y = img_y + img_h + 40
    put(scene_data.get("caption", ""), f_cap, TEXT, 70, 3)

    sub = (scene_data.get("sub") or "").strip()
    if sub:
        y += 8
        put(sub, f_sub, MUTED, 48, 2)

    extra = (scene_data.get("detail") or "").strip()
    if extra:
        put(extra, f_sub, GOLD, 48, 1)

    # ── 구매 안내 ────────────────────────────────────────────
    # 릴스에서는 화면 맨 아래를 계정명과 캡션이 덮는다. 안전영역 안에 둔다.
    cta = "프로필 링크에서 구매"
    draw.rectangle([(L, cy), (R, cy + 84)], fill=ACCENT)
    cw_ = draw.textlength(cta, font=f_cta)
    draw.text((L + (inner - cw_) / 2, cy + 18), cta, fill="#0b0c10", font=f_cta)

    return canvas

# ════════════════════════════════════════════════════════════════
# 5. EstateReels 비디오 렌더링 메인 파이프라인 (타임스탬프 신규 파일 생성)
# ════════════════════════════════════════════════════════════════
def generate_product_reels_video(product_id_or_url: str, concept_id: str = "price_focus",
                                 script_lines: list = None, tts_rate: str = "+12%") -> str:
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

    # 호출자가 대사를 직접 준 경우 그것으로 갈아끼운다.
    # video_pipeline 은 가드레일을 통과한 대사를 만들어 넘긴다 — 스토리보드가
    # 자체 생성한 문구보다 검증된 문장을 쓰는 편이 낫다.
    if script_lines:
        for i, sc in enumerate(storyboard):
            if i < len(script_lines):
                sc["narration"] = script_lines[i]
                sc["caption"] = script_lines[i]   # 렌더러가 줄을 접는다. 자르지 않는다.
        # 대사가 씬보다 적으면 남는 씬을 잘라 낸다(빈 나레이션으로 정적이 남는 걸 막는다)
        storyboard = storyboard[:max(1, len(script_lines))]

    # 4. 장면별 영상 만들기
    #
    # 예전에는 moviepy 로 붙였는데, moviepy 2.2.1 은 pillow<12.0 을 요구한다.
    # 이 PC 의 rembg(>=12.1)·pdfplumber(>=12.2) 와 같이 설치될 수 없어 걷어냈다.
    # 지금은 video_assemble 이 ffmpeg 를 직접 부른다. 하는 일이 프레임 잇기와
    # 오디오 얹기뿐이라 중간 라이브러리가 필요 없다.
    import video_assemble as VA

    scene_files = []
    temp_files = []
    for sc in storyboard:
        seq = sc["seq"]
        audio_file = os.path.join(REELS_DIR, f"audio_{product_id}_sc{seq}_{timestamp_str}.mp3")

        generate_scene_tts(sc["narration"], audio_file, rate=tts_rate)
        temp_files.append(audio_file)

        # 장면 길이는 나레이션 길이에 맞춘다. 말이 끝나기 전에 화면이 넘어가면
        # 다음 장면에서 앞 문장이 이어져 들린다.
        # 뒤에 0.9초를 더 둔다 — 말이 끝나자마자 넘어가면 자막을 끝까지 못 읽는다.
        dur = VA.audio_duration(audio_file)
        duration = max(3.5, dur + 0.9) if dur else 4.0

        fps = RENDER_FPS
        num_frames = max(1, int(duration * fps))
        frames = [
            render_estatereels_frame(photo=sc["photo"], scene_data=sc,
                                     progress=i / max(1, num_frames - 1))
            for i in range(num_frames)
        ]

        clip_path = os.path.join(REELS_DIR, f"_scene_{product_id}_{seq}_{timestamp_str}.mp4")
        try:
            VA.scene_clip(frames, audio_file, clip_path, fps=fps)
            scene_files.append(clip_path)
            temp_files.append(clip_path)
        except Exception as e:
            print(f"[EstateReels Clip Error] 장면 {seq} 실패: {e}")

    # 5. 최종 MP4 내보내기
    #
    # 예전에는 여기서 만들어지지도 않은 파일의 경로를 반환했다. 호출한 쪽은
    # 성공으로 알고 원장에 기록했고, 정작 파일은 없었다. 이제는 예외를 던진다.
    if not scene_files:
        raise RuntimeError(
            f"장면을 하나도 만들지 못했습니다 (상품 {product_id}). "
            "ffmpeg 설치 여부와 위 [Clip Error] 를 확인하세요.")

    try:
        VA.concat(scene_files, output_mp4_timestamped)
        try:
            import shutil
            shutil.copy2(output_mp4_timestamped, output_mp4_static)
        except Exception as fe:
            print(f"[EstateReels Generator Note] 대표 파일 갱신 실패(잠김): {fe}")
        print(f"[EstateReels Generator] 영상 완성: {output_mp4_timestamped}")
    finally:
        for f in temp_files:
            try:
                os.remove(f)
            except Exception:
                pass

    if not os.path.exists(output_mp4_timestamped):
        raise RuntimeError(f"영상 파일이 만들어지지 않았습니다: {output_mp4_timestamped}")
    return output_mp4_timestamped

if __name__ == "__main__":
    print("[EstateReels Generator] Testing timestamped video creation...")
    mp4_path = generate_product_reels_video("CP100_009")
    print(f"[EstateReels Generator] BRAND NEW Video Path: {mp4_path}")
