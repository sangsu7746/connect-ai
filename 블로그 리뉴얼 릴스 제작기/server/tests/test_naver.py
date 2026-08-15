import httpx
from core import naver

FAKE = {"items": [{
    "title": "전세 <b>보증보험</b> 가입법 &amp; 비용",
    "link": "https://blog.naver.com/abc/123",
    "description": "보증료는 <b>연 0.128%</b>입니다",
    "bloggername": "부동산왕", "postdate": "20260810",
}]}

def test_search_blog_parses(monkeypatch):
    def fake_get(url, params=None, headers=None, timeout=None):
        assert "openapi.naver.com" in url
        assert headers["X-Naver-Client-Id"] == "test-id"
        return httpx.Response(200, json=FAKE, request=httpx.Request("GET", url))
    monkeypatch.setattr(naver.settings, "naver_client_id", "test-id")
    monkeypatch.setattr(naver.settings, "naver_client_secret", "test-sec")
    monkeypatch.setattr(httpx, "get", fake_get)
    items = naver.search_blog("전세 보증보험")
    assert items[0]["title"] == "전세 보증보험 가입법 & 비용"
    assert items[0]["summary"] == "보증료는 연 0.128%입니다"
    assert items[0]["source"] == "naver"
    assert items[0]["posted_at"] == "20260810"

def test_clean_html():
    assert naver.clean_html("a<b>b</b> &quot;c&quot; &lt;d&gt;") == 'ab "c" <d>'
