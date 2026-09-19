"""
상품평 사진을 릴스 소재로 쓸 수 있게 고르는 모듈.

## 이 사진들의 성격
상품평 사진은 구매자가 직접 찍어 올린 것이다. 저작권은 찍은 사람에게 있고,
쿠팡 약관이 주는 이용 권한은 쿠팡에게 가는 것이지 파트너스에게 오는 게 아니다.
사람이 찍혀 있으면 초상권도 별개로 걸린다.

사용 여부는 운영자가 판단했다. 이 모듈이 하는 일은 그 판단 위에서 위험이 큰 것부터
걸러 내는 것이다:

  1. 얼굴이 보이는 사진은 버린다 (초상권)
  2. 스크린샷·문서로 보이는 사진은 버린다 (주문내역·개인정보가 찍힌 것들)
  3. 너무 어둡거나 작아 알아볼 수 없는 사진은 버린다 (품질)

걸러도 저작권 문제 자체는 남는다. 그건 코드로 없앨 수 없다.
"""
import io
import os

import numpy as np
import requests
from PIL import Image

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(BASE_DIR, "temp_review_imgs")

#: 릴스 카드에 넣을 최소 크기. 이보다 작으면 확대했을 때 뭉갠다.
MIN_SIDE = 500

_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Referer": "https://www.coupang.com/",
}

_cascade = None


def _face_detector():
    """얼굴 검출기. cv2 가 없으면 None — 그때는 사람 사진을 못 거른다."""
    global _cascade
    if _cascade is not None:
        return _cascade or None
    try:
        import cv2
        path = os.path.join(cv2.data.haarcascades,
                            "haarcascade_frontalface_default.xml")
        _cascade = cv2.CascadeClassifier(path) if os.path.exists(path) else False
    except Exception:
        _cascade = False
    return _cascade or None


def has_face(img: Image.Image) -> bool:
    """
    사람 얼굴이 보이는가.

    정면 얼굴만 잡는 고전적인 검출기라 옆얼굴·가려진 얼굴은 놓친다.
    완벽한 필터가 아니라 '명백한 것부터 걸러 내는' 장치다.
    """
    det = _face_detector()
    if det is None:
        # 검출기가 없으면 판단할 수 없다. 안전한 쪽(사람이 있다고 보고 버림)으로 답한다.
        return True
    try:
        import cv2
        small = img.convert("L")
        # 검출 비용을 줄이려고 640px 로 줄인다. 얼굴이 그보다 작게 찍혔으면
        # 릴스에서도 알아볼 수 없는 크기다.
        if max(small.size) > 640:
            r = 640 / max(small.size)
            small = small.resize((max(1, int(small.width * r)),
                                  max(1, int(small.height * r))))
        gray = np.array(small)
        faces = det.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5,
                                     minSize=(40, 40))
        return len(faces) > 0
    except Exception:
        return True


def judge_with_vision(img: Image.Image) -> str:
    """
    사진을 모델에게 보여 주고 쓸 수 있는지 묻는다.
    반환: "ok" | "person" | "private" | "unknown"

    ## 왜 색으로 안 하고 모델에게 묻는가
    처음에는 피부색 화소 비율로 사람을 걸러 보려 했다(YCrCb 범위).
    이 도메인에서는 못 쓴다 — 아메리카노 상품평 24장에 걸어 보니 15장이 걸렸는데,
    실제로 확인하니 대부분 그냥 상품 사진이었다. 갈색 커피, 원목 식탁, 골판지 상자가
    전부 피부색 범위에 들어간다. 컵에 든 커피가 피부 비율 0.84 로 제일 높게 나왔다.
    색만으로는 사람과 커피를 구분할 수 없다.

    Haar 얼굴 검출기는 정면 얼굴만 잡아서 옆얼굴·눈 클로즈업을 놓친다.
    결국 '무엇이 찍혔는지'를 아는 판단이 필요하다. 블로그 쪽에서 수집 글 이미지의
    개인 서류를 거를 때 쓰는 방식과 같다.

    크레딧이 없거나 오류가 나면 "unknown" 을 준다. 그때는 호출한 쪽이 정한다.
    """
    try:
        import config as cfg
        import ai_writer
        from google import genai
        key = cfg.load_config().get("gemini_api_key", "")
        if not key:
            return "unknown"

        buf = io.BytesIO()
        thumb = img.copy()
        thumb.thumbnail((512, 512))
        thumb.save(buf, format="JPEG", quality=80)

        prompt = (
            "이 사진을 광고 영상에 쓰려고 한다. 다음 중 하나만 답하라.\n"
            "person  — 사람의 얼굴이나 신체가 알아볼 수 있게 찍혀 있다\n"
            "private — 주문내역·영수증·문자·서류처럼 개인정보가 보인다\n"
            "ok      — 물건이나 풍경만 찍혀 있다 (물건을 든 손 정도는 ok 로 본다)\n"
            "다른 말은 쓰지 마라."
        )
        client = genai.Client(api_key=key)
        r = client.models.generate_content(
            model=ai_writer.MODEL,
            contents=[{"inline_data": {"mime_type": "image/jpeg",
                                       "data": buf.getvalue()}}, prompt])
        ans = (r.text or "").strip().lower()
        for k in ("person", "private", "ok"):
            if k in ans:
                return k
        return "unknown"
    except Exception:
        return "unknown"


def looks_like_document(img: Image.Image) -> bool:
    """
    주문내역 캡처·영수증·문자 스크린샷처럼 보이는가.

    이런 사진에는 주소·주문번호·전화번호가 그대로 찍혀 있다. 광고에 실으면
    남의 개인정보를 퍼뜨리는 것이 된다.
    실제로 블로그 쪽 이미지 판독에서도 같은 이유로 개인 서류를 걸러 냈다.

    판정: 흰 바탕이 압도적이고 색이 거의 없으면 문서로 본다.
    """
    try:
        small = img.convert("RGB").resize((160, 160))
        a = np.asarray(small).astype(np.int16)
        bright = (a.mean(axis=2) > 225).mean()          # 흰 배경 비율
        sat = (a.max(axis=2) - a.min(axis=2)).mean()    # 채도(높으면 사진)
        return bright > 0.55 and sat < 22
    except Exception:
        return False


def _download(url: str, pid: str, idx: int):
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"rev_{pid}_{idx}.jpg")
    if not os.path.exists(path):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=10)
            if r.status_code != 200 or len(r.content) < 3000:
                return None
            with open(path, "wb") as f:
                f.write(r.content)
        except Exception:
            return None
    try:
        return Image.open(path).convert("RGB")
    except Exception:
        return None


def usable_review_photos(product_info: dict, want: int = 3, log=None,
                         require_vision: bool = True) -> list:
    """
    쓸 만한 상품평 사진을 want 장까지 고른다.

    버린 이유를 남긴다 — 몇 장을 왜 버렸는지 안 보이면, 필터가 죽어 있어도 모른다.

    require_vision=False 로 두면 모델 판독을 건너뛴다. 얼굴 검출기만 남으므로
    옆얼굴·신체 클로즈업이 통과할 수 있다. 그 위험을 아는 경우에만 쓸 것.
    """
    import json

    urls = product_info.get("review_images") or []
    if isinstance(urls, str):
        try:
            urls = json.loads(urls)
        except Exception:
            urls = []
    if not isinstance(urls, list) or not urls:
        return []

    pid = str(product_info.get("product_id", "x"))
    picked, reasons = [], {"작음": 0, "얼굴": 0, "사람": 0, "개인정보": 0,
                           "판독불가": 0, "실패": 0}
    vision_dead = False    # 크레딧 소진 등으로 판독이 안 되면 한 번만 확인하고 만다

    for i, u in enumerate(urls):
        if len(picked) >= want:
            break
        img = _download(u, pid, i)
        if img is None:
            reasons["실패"] += 1
            continue
        if min(img.size) < MIN_SIDE:
            reasons["작음"] += 1
            continue
        if looks_like_document(img):
            reasons["개인정보"] += 1
            continue
        if has_face(img):
            reasons["얼굴"] += 1
            continue

        # 얼굴 검출기가 놓치는 것(옆얼굴·눈 클로즈업 등)은 모델에게 묻는다.
        if require_vision:
            verdict = judge_with_vision(img)
            if verdict == "person":
                reasons["사람"] += 1
                continue
            if verdict == "private":
                reasons["개인정보"] += 1
                continue
            if verdict == "unknown":
                # 판독이 안 되면(크레딧 소진·오류) 상품평 사진은 아예 쓰지 않는다.
                # 남의 얼굴이 광고에 실리는 쪽이, 영상 한 편 못 만드는 것보다 나쁘다.
                #
                # 여기서 continue 로 넘어가면 안 된다 — 다음 장도 똑같이 판독이 안 될
                # 텐데, 그때 검사 없이 통과시키면 필터가 있으나 마나가 된다.
                vision_dead = True
                break

        picked.append(img)

    if vision_dead:
        # 판독을 못 했으면 이미 고른 것도 버린다. 앞 몇 장만 검사가 된 상태로
        # 섞어 쓰면 어디까지 확인된 것인지 알 수 없다.
        picked = []
        if log:
            log("    ⛔ 상품평 사진 판독 불가(Gemini 크레딧/오류) — 이번에는 쓰지 않습니다.")
        return []

    if log:
        dropped = ", ".join(f"{k} {v}장" for k, v in reasons.items() if v)
        log(f"    상품평 사진 {len(picked)}장 채택"
            + (f" (제외: {dropped})" if dropped else ""))
    return picked


def selftest() -> None:
    """필터가 살아 있는지 확인한다."""
    white = Image.new("RGB", (800, 800), (255, 255, 255))
    print("흰 문서 판정:", looks_like_document(white), "(True 여야 함)")
    photo = Image.fromarray(
        (np.random.rand(800, 800, 3) * 255).astype("uint8"), "RGB")
    print("잡음 사진 판정:", looks_like_document(photo), "(False 여야 함)")
    print("얼굴 검출기:", "있음" if _face_detector() is not None else "없음")
    print("모델 판독:", judge_with_vision(photo), "(크레딧 있으면 ok/person/private)")


if __name__ == "__main__":
    selftest()
