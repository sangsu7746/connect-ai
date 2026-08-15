from core import crawler
import httpx

def test_to_mobile_naver():
    assert crawler.to_mobile_naver("https://blog.naver.com/abc/223999") == \
        "https://m.blog.naver.com/abc/223999"
    assert crawler.to_mobile_naver("https://x.tistory.com/1") is None

def test_extract_naver_smarteditor():
    html = '<div class="se-main-container"><p>본문 첫줄</p><p>둘째 줄 3,000원</p></div>'
    assert crawler.extract_naver(html) == "본문 첫줄\n둘째 줄 3,000원"

def test_extract_naver_legacy():
    html = '<div id="postViewArea"><p>옛날 에디터 본문</p></div>'
    assert crawler.extract_naver(html) == "옛날 에디터 본문"

def test_fetch_content_falls_back_to_jina(monkeypatch):
    monkeypatch.setattr(crawler, "_get", lambda url: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(crawler, "fetch_jina", lambda url: "지나 본문")
    assert crawler.fetch_content("https://x.tistory.com/1") == "지나 본문"

def test_to_mobile_naver_postview_style():
    assert crawler.to_mobile_naver(
        "https://blog.naver.com/PostView.naver?blogId=abc&logNo=223999"
    ) == "https://m.blog.naver.com/abc/223999"

def test_fetch_content_short_text_falls_back_to_jina(monkeypatch):
    monkeypatch.setattr(crawler, "_get", lambda url: "<html><body><p>짧음</p></body></html>")
    monkeypatch.setattr(crawler, "extract_generic", lambda html, url: "80자 미만 본문")
    monkeypatch.setattr(crawler, "fetch_jina", lambda url: "지나 긴 본문")
    assert crawler.fetch_content("https://x.tistory.com/1") == "지나 긴 본문"

def test_fetch_jina_status_and_exception(monkeypatch):
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: httpx.Response(
        200, text="본문", request=httpx.Request("GET", url)))
    assert crawler.fetch_jina("https://x.com/1") == "본문"
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None: httpx.Response(
        451, request=httpx.Request("GET", url)))
    assert crawler.fetch_jina("https://x.com/1") == ""
    def boom(url, headers=None, timeout=None):
        raise OSError("net down")
    monkeypatch.setattr(httpx, "get", boom)
    assert crawler.fetch_jina("https://x.com/1") == ""
