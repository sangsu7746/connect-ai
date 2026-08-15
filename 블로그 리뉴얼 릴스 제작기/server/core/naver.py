import html, re
import httpx
from .config import settings

def clean_html(s: str) -> str:
    return html.unescape(re.sub(r"</?b>", "", s or "")).strip()

def _headers() -> dict:
    return {"X-Naver-Client-Id": settings.naver_client_id,
            "X-Naver-Client-Secret": settings.naver_client_secret}

def search_blog(query: str, display: int = 10) -> list[dict]:
    r = httpx.get("https://openapi.naver.com/v1/search/blog.json",
                  params={"query": query, "display": display, "sort": "sim"},
                  headers=_headers(), timeout=10)
    r.raise_for_status()
    return [{
        "source": "naver",
        "title": clean_html(it.get("title", "")),
        "url": it.get("link", ""),
        "summary": clean_html(it.get("description", "")),
        "blogger": it.get("bloggername", ""),
        "posted_at": it.get("postdate", ""),
    } for it in r.json().get("items", [])]
