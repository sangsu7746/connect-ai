from core import crawler

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
