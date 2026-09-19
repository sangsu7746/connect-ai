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


NAVER_IMG_HTML = """
<div class="se-main-container">
  <p>본문</p>
  <img class="se-image-resource" width="886" src="https://x.pstatic.net/big1.jpg">
  <img class="se-image-resource" width="886" data-lazy-src="https://x.pstatic.net/big2.jpg">
  <img class="icon" width="20" src="https://x.pstatic.net/icon.gif">
  <img class="se-sticker-image" width="300" src="https://x.pstatic.net/sticker.png">
  <img src="https://ssl.pstatic.net/static/blog/profile.png">
</div>
"""


def test_extract_images_keeps_content_only():
    urls = crawler.extract_images(NAVER_IMG_HTML, "https://blog.naver.com/a/1")
    assert "https://x.pstatic.net/big1.jpg" in urls
    assert "https://x.pstatic.net/big2.jpg" in urls      # lazy-src 도 수집
    assert not any("icon" in u for u in urls)            # 작은 아이콘 제외
    assert not any("sticker" in u for u in urls)         # 스티커 제외
    assert not any("profile" in u for u in urls)         # 프로필 제외


def test_extract_images_caps_and_dedups():
    many = '<div class="se-main-container">' + "".join(
        f'<img class="se-image-resource" width="886" src="https://x.net/{i}.jpg">'
        for i in range(12)) + '<img class="se-image-resource" width="886" src="https://x.net/0.jpg"></div>'
    urls = crawler.extract_images(many, "https://blog.naver.com/a/1")
    assert len(urls) == crawler.MAX_IMAGES
    assert len(set(urls)) == len(urls)                   # 중복 없음


def test_extract_images_relative_to_absolute():
    html = '<article><img width="800" src="/img/chart.png"></article>'
    urls = crawler.extract_images(html, "https://blog.example.com/post/1")
    assert urls == ["https://blog.example.com/img/chart.png"]


def test_extract_images_empty_on_no_content():
    assert crawler.extract_images("<html><body></body></html>", "https://x.com/1") == []
