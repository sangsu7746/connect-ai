import re
import httpx
import trafilatura
from bs4 import BeautifulSoup

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

def _get(url: str) -> str:
    r = httpx.get(url, headers={"User-Agent": UA}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text

def to_mobile_naver(url: str) -> str | None:
    m = re.match(r"https?://blog\.naver\.com/([^/]+)/(\d+)", url)
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
