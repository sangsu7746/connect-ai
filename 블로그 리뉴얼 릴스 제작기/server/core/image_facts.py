"""수집 글의 이미지에서 '사실'만 읽어낸다 (spec §12-B).

블로그 글은 보증료율표·한도표처럼 핵심 수치를 이미지로 넣는 경우가 많다.
본문 텍스트만 읽으면 그 숫자를 통째로 놓친다 — 대본·글의 근거가 얇아지고,
정작 중요한 수치는 날조 게이트에 걸려 쓰지도 못한다.

여기서 가져오는 것은 **사실뿐**이고 그림 자체는 쓰지 않는다. 사실은 저작권
보호 대상이 아니므로(표현만 보호된다) 남의 이미지를 복제하지 않고도
그 안의 정보를 활용할 수 있다.

실패는 전부 조용히 건너뛴다 — 이미지 판독이 안 된다고 수집이 멈추면 안 된다.
"""
import io

import httpx
from PIL import Image

from . import gemini
from .purple_cow_blog import extract_numbers

#: 비전 호출에 보낼 이미지의 최대 변 길이. 원본 그대로 보내면 요청이 커지고
#: 판독 정확도는 별로 오르지 않는다.
MAX_EDGE = 768

_TIMEOUT = 20
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

_PROMPT = """이 이미지들은 블로그 글에 실린 표·인포그래픽·안내 이미지다.
이미지에 **적혀 있는** 수치·조건·기준만 한국어 문장으로 옮겨라.

규칙:
- 이미지에 없는 내용을 추측하거나 보충하지 마라.
- 숫자(금액·비율·기간·한도)가 들어간 사실만 쓴다. 숫자가 없으면 그 항목은 버린다.
- 한 문장에 하나의 사실만 담고, 주어를 명시한다("이것"·"해당" 금지).
- 읽을 수 있는 사실이 없으면 빈 배열을 출력한다.

출력은 JSON 문자열 배열 하나만: ["사실1", "사실2"]"""


def _download(url: str) -> bytes:
    """이미지를 받아 JPEG로 정규화하고 긴 변을 MAX_EDGE로 줄인다.

    PNG로 보내면 사진 한 장이 400KB를 넘어 요청이 과도하게 커진다(실측).
    판독 목적에는 JPEG 품질 82면 충분하고 용량은 1/6 수준이다.
    """
    r = httpx.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT,
                  follow_redirects=True)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > MAX_EDGE:
        img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=82, optimize=True)
    return buf.getvalue()


def extract_facts(post: dict) -> list[dict]:
    """글 하나의 이미지들에서 사실을 뽑아 팩트 시트 행으로 돌려준다.

    반환 형태는 analysis.build_fact_sheet 와 같고, 이미지 출처임을 알 수 있게
    from_image=True 를 단다.
    """
    urls = post.get("image_urls") or []
    if not urls or not gemini.available():
        return []

    images: list[bytes] = []
    for url in urls:
        try:
            images.append(_download(url))
        except Exception:
            continue          # 개별 이미지 실패는 건너뛴다
    if not images:
        return []

    try:
        parsed = gemini.parse_json(
            gemini.generate_vision(_PROMPT, images, mime="image/jpeg"))
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []

    facts: list[dict] = []
    seen: set[str] = set()
    for item in parsed:
        text = str(item).strip()
        # 숫자 없는 문장은 게이트의 근거가 못 되므로 팩트로 취급하지 않는다
        if not text or text in seen or not extract_numbers(text):
            continue
        seen.add(text)
        facts.append({"fact": text,
                      "source_title": post.get("title", ""),
                      "source_url": post.get("url", ""),
                      "from_image": True})
    return facts
