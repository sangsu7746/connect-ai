import httpx
from core import google_search as g

FAKE = {"items": [
    {"title": "ISA 계좌 총정리", "link": "https://abc.tistory.com/12",
     "snippet": "비과세 한도 200만원"},
    {"title": "ISA 광고", "link": "https://ad.example.com/x",
     "snippet": "광고"},
    {"title": "브런치 글", "link": "https://brunch.co.kr/@x/3",
     "snippet": "에세이"},
]}

def test_cse_filters_blog_domains(monkeypatch):
    monkeypatch.setattr(g.settings, "google_cse_key", "k")
    monkeypatch.setattr(g.settings, "google_cse_id", "cx")
    monkeypatch.setattr(httpx, "get", lambda *a, **kw: httpx.Response(
        200, json=FAKE, request=httpx.Request("GET", "u")))
    items = g.search_blog("ISA")
    assert [i["url"] for i in items] == [
        "https://abc.tistory.com/12", "https://brunch.co.kr/@x/3"]
    assert all(i["source"] == "google" for i in items)

def test_no_key_returns_empty(monkeypatch):
    monkeypatch.setattr(g.settings, "google_cse_key", "")
    assert g.search_blog("x") == []
    assert g.available() is False

def test_parse_serp_html():
    html = '''<div class="g"><a href="https://x.tistory.com/1"><h3>제목A</h3></a>
              <div class="VwiC3b">요약A</div></div>
              <div class="g"><a href="https://news.example.com/2"><h3>뉴스</h3></a></div>'''
    items = g.parse_serp_html(html)
    assert items == [{"source": "google", "title": "제목A",
                      "url": "https://x.tistory.com/1", "summary": "요약A",
                      "blogger": "", "posted_at": ""}]
