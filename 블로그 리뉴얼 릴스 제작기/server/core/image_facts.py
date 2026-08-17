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
import re

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
- **누구에게나 적용되는 일반 기준만** 옮긴다. 계약서·대출 명세서·신청서·고지서처럼
  특정 개인의 사정이 적힌 서류는 통째로 건너뛴다 — 그 사람의 계약 금액, 대출 만기일,
  제출 기한, 이름, 주소, 계좌번호는 옮기지 마라.
  예) "대출금 기한연장은 만기일 1개월 전부터 가능하다"는 일반 규칙이니 쓴다.
      "이 대출의 만기일은 2026년 6월 21일이다"는 한 사람의 사정이니 버린다.
- 읽을 수 있는 사실이 없으면 빈 배열을 출력한다.

출력은 JSON 문자열 배열 하나만: ["사실1", "사실2"]"""

#: 개인의 서류에만 나오는 말. 이게 있으면 그 문장은 통째로 버린다.
#: "계약서"·"대출계좌"를 통째로 막았더니 "가입을 위한 계약서의 기준일은 2020년
#: 4월 1일 이후여야 한다"(HUG 가입 요건) 같은 **일반 규칙**까지 걸렸다(실측).
#: 그래서 개별 서류의 내용을 가리키는 표현("계약서에 적힌")으로 좁힌다.
_PERSONAL_DOC = re.compile(
    r"(계약서\s*(에\s*적힌|상|에\s*기재)|신청서\s*(에\s*적힌|상)|"
    r"매매대금|중도금|잔금|"
    r"금\s*[\d,]{7,}\s*원|"          # 계약서 특유의 금액 표기 "금 500,000,000원"
    r"등기권리증|등기필증|"
    r"성명|생년월일|주민등록번호|계좌번호|연락처|휴대폰\s*번호)")

#: 절대 날짜(2026년 6월 21일 / 2026.06.21). 일반 기준은 "30일 이내"처럼 기간으로 쓰고,
#: 특정 날짜가 박히면 그건 대개 그 사람 한 명의 일정이다.
_ABS_DATE = re.compile(r"\d{4}\s*[년.\-/]\s*\d{1,2}\s*[월.\-/]\s*\d{1,2}\s*일?")

#: 절대 날짜가 개인 일정을 가리키게 만드는 말.
_PERSONAL_DATE_CTX = re.compile(r"(만기|계약|제출|약정|신청|승인|실행|납부|상환)")

#: 같은 절대 날짜라도 제도의 경계선을 그으면 공적 사실이다 — "2020년 4월 1일 이후",
#: "2026년 1월 1일부터 시행". 개인 일정은 "만기일은 X이다"처럼 한 시점을 지목한다.
_POLICY_DATE_CTX = re.compile(r"(이후|이전|부터|시행|개정|신설|폐지|기준으로)")


def is_personal(text: str) -> bool:
    """특정 개인의 서류에서 나온 문장인가 (spec §12-B).

    사실은 저작권 대상이 아니라서 이미지에서 옮겨 써도 되지만, **개인정보는 다르다**.
    블로거가 자기 계약서·대출 명세서를 찍어 올린 경우 판독은 정확해도 그 숫자를
    공개 영상에 실으면 남의 개인정보를 다시 퍼뜨리는 셈이 된다. 게다가 한 사람의
    날짜가 일반 규칙처럼 읽혀 시청자에게 틀린 정보가 된다.

    날조 게이트는 이걸 못 잡는다 — corpus_text에 이미지 사실이 들어가는 순간
    이 숫자들은 "수집 자료에 있는 정당한 숫자"가 되어 통과한다. 그래서 여기서 막는다.
    """
    if _PERSONAL_DOC.search(text):
        return True
    if not (_ABS_DATE.search(text) and _PERSONAL_DATE_CTX.search(text)):
        return False
    return not _POLICY_DATE_CTX.search(text)     # 제도 경계선이면 살린다


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
        # 프롬프트로 한 번 거르고 여기서 한 번 더 거른다 — 공개 영상에 남의
        # 계약 금액이 실리는 쪽이, 쓸 만한 사실 몇 개를 잃는 쪽보다 나쁘다
        if is_personal(text):
            continue
        seen.add(text)
        facts.append({"fact": text,
                      "source_title": post.get("title", ""),
                      "source_url": post.get("url", ""),
                      "from_image": True})
    return facts
