import html, re
import httpx
import datetime as _dt
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

def rise_pct(last: float, prev: float) -> float:
    return round((last - prev) / max(prev, 1.0) * 100.0, 1)

def datalab_ratios(keywords: list[str]) -> dict[str, tuple[float, float]]:
    """키워드별 (최근주, 이전주) 검색 트렌드 ratio. 5개씩 배치 호출."""
    end = _dt.date.today() - _dt.timedelta(days=1)
    start = end - _dt.timedelta(weeks=8)
    out: dict[str, tuple[float, float]] = {}
    for i in range(0, len(keywords), 5):
        batch = keywords[i:i + 5]
        body = {
            "startDate": start.isoformat(), "endDate": end.isoformat(),
            "timeUnit": "week",
            "keywordGroups": [{"groupName": k, "keywords": [k]} for k in batch],
        }
        r = httpx.post("https://openapi.naver.com/v1/datalab/search",
                       json=body,
                       headers={**_headers(), "Content-Type": "application/json"},
                       timeout=15)
        r.raise_for_status()
        for res in r.json().get("results", []):
            data = res.get("data", [])
            last = data[-1]["ratio"] if data else 0.0
            prev = data[-2]["ratio"] if len(data) > 1 else 0.0
            out[res["title"]] = (last, prev)
    return out
