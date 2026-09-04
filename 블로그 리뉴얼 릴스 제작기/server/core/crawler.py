import re
import httpx
import trafilatura
from urllib.parse import urljoin

from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def _get(url: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def to_mobile_naver(url: str) -> str | None:
    m = re.match(r"https?://(?:m\.)?blog\.naver\.com/([^/?]+)/(\d+)", url)
    if m and m.group(1) != "PostView.naver":
        return f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
    m = re.search(r"https?://(?:m\.)?blog\.naver\.com/PostView\.naver\?.*?blogId=([^&]+).*?logNo=(\d+)", url)
    if m:
        return f"https://m.blog.naver.com/{m.group(1)}/{m.group(2)}"
    return None

def extract_naver(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    box = soup.select_one("div.se-main-container") or soup.select_one("#postViewArea")
    if not box:
        return ""
    lines = [t.strip() for t in box.stripped_strings]
    return "\n".join(x for x in lines if x)

def extract_generic(html: str, url: str) -> str:
    return trafilatura.extract(html, url=url) or ""

def fetch_jina(url: str) -> str:
    try:
        r = httpx.get(f"https://r.jina.ai/{url}",
                      headers={"User-Agent": UA}, timeout=20)
        return r.text if r.status_code == 200 else ""
    except Exception:
        return ""

def fetch_content(url: str) -> str:
    try:
        mobile = to_mobile_naver(url)
        if mobile:
            text = extract_naver(_get(mobile))
        else:
            text = extract_generic(_get(url), url)
        if text and len(text) >= 80:
            return text
    except Exception:
        pass
    return fetch_jina(url)


#: 글당 수집할 본문 이미지 상한. 비전 호출 비용과 직결되므로 넉넉히 잡지 않는다.
MAX_IMAGES = 5

#: 본문 이미지로 볼 최소 폭(px). 아이콘·이모티콘·버튼을 걸러낸다.
_MIN_IMG_WIDTH = 300

#: 본문이 아닌 것이 분명한 이미지 — 스티커·프로필·배지·광고
_SKIP_URL = re.compile(r"(sticker|profile|emoticon|blogpfthumb|badge|banner|"
                       r"ico_|icon_|/icon/|btn_|logo)", re.I)
_SKIP_CLASS = re.compile(r"(sticker|emoticon|profile|icon|badge)", re.I)


def _img_width(tag) -> int:
    """폭 힌트를 정수로. 없으면 0(판단 보류)."""
    for key in ("width", "data-width", "data-origin-width"):
        v = (tag.get(key) or "").strip()
        if v.isdigit():
            return int(v)
    return 0


def extract_images(html: str, page_url: str) -> list[str]:
    """본문 영역의 이미지 URL만 뽑는다 (spec §12-B).

    수집한 그림 자체를 쓰려는 게 아니라 담긴 '사실'을 읽기 위한 것이므로,
    표·인포그래픽처럼 큰 이미지만 남기고 장식성 요소는 버린다.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    box = (soup.select_one("div.se-main-container")
           or soup.select_one("#postViewArea")
           or soup.select_one("article")
           or soup.select_one("main"))
    if box is None:
        return []

    urls: list[str] = []
    for tag in box.find_all("img"):
        src = (tag.get("data-lazy-src") or tag.get("data-src")
               or tag.get("src") or "").strip()
        if not src or src.startswith("data:"):
            continue
        classes = " ".join(tag.get("class") or [])
        if _SKIP_CLASS.search(classes) or _SKIP_URL.search(src):
            continue
        w = _img_width(tag)
        if w and w < _MIN_IMG_WIDTH:
            continue
        absolute = urljoin(page_url, src)
        if absolute not in urls:
            urls.append(absolute)
        if len(urls) >= MAX_IMAGES:
            break
    return urls


def fetch_images(url: str) -> list[str]:
    """글 URL에서 본문 이미지 주소만 가져온다. 실패는 빈 목록(수집을 멈추지 않는다)."""
    try:
        mobile = to_mobile_naver(url)
        target = mobile or url
        return extract_images(_get(target), target)
    except Exception:
        return []
