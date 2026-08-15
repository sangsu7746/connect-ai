import httpx
from bs4 import BeautifulSoup
from .config import settings

BLOG_DOMAINS = ("tistory.com", "brunch.co.kr", "blog.naver.com",
                "velog.io", "medium.com", "post.naver.com")

def _is_blog(url: str) -> bool:
    return any(d in url for d in BLOG_DOMAINS)

def available() -> bool:
    return bool(settings.google_cse_key and settings.google_cse_id)

def search_blog(query: str, num: int = 10) -> list[dict]:
    if not available():
        return []
    r = httpx.get("https://www.googleapis.com/customsearch/v1",
                  params={"key": settings.google_cse_key,
                          "cx": settings.google_cse_id,
                          "q": query, "num": min(num, 10)},
                  timeout=10)
    r.raise_for_status()
    return [{
        "source": "google",
        "title": it.get("title", ""),
        "url": it.get("link", ""),
        "summary": it.get("snippet", ""),
        "blogger": "", "posted_at": "",
    } for it in r.json().get("items", []) if _is_blog(it.get("link", ""))]

def parse_serp_html(html: str) -> list[dict]:
    """Playwright로 받은 구글 SERP HTML에서 블로그 결과만 추출 (CSE 키 부재 시 폴백)."""
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for block in soup.select("div.g"):
        a = block.select_one("a[href]")
        h3 = block.select_one("h3")
        if not a or not h3 or not _is_blog(a["href"]):
            continue
        sn = block.select_one("div.VwiC3b")
        out.append({"source": "google", "title": h3.get_text(strip=True),
                    "url": a["href"],
                    "summary": sn.get_text(strip=True) if sn else "",
                    "blogger": "", "posted_at": ""})
    return out

def search_blog_playwright(query: str, num: int = 10) -> list[dict]:
    """CSE 키가 없을 때의 폴백. 설치된 Chrome 채널로 구글 SERP를 연다.
    실패는 조용히 [] — 수집은 네이버만으로도 진행돼야 한다 (spec §10)."""
    from urllib.parse import quote_plus
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(channel="chrome", headless=True)
            except Exception:
                browser = p.chromium.launch(headless=True)
            page = browser.new_page(locale="ko-KR")
            page.goto(f"https://www.google.com/search?q={quote_plus(query)}&num={num}",
                      timeout=15000)
            html = page.content()
            browser.close()
        return parse_serp_html(html)
    except Exception:
        return []
