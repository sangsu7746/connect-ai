import httpx
import pytest
from core import image_facts

POST = {"title": "전세보증보험 총정리", "url": "https://blog.naver.com/a/1",
        "image_urls": ["https://x.net/a.jpg", "https://x.net/b.jpg"]}

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 200


def _setup(monkeypatch, gen_out='["보증료는 연 0.128%다.", "한도는 7억원이다."]'):
    monkeypatch.setattr(image_facts.gemini, "available", lambda: True)
    monkeypatch.setattr(image_facts.gemini, "generate_vision",
                        lambda prompt, images, **kw: gen_out)
    monkeypatch.setattr(image_facts, "_download", lambda url: PNG)


def test_extract_returns_fact_sheet_rows(monkeypatch):
    _setup(monkeypatch)
    facts = image_facts.extract_facts(POST)
    assert len(facts) == 2
    assert facts[0]["fact"] == "보증료는 연 0.128%다."
    assert facts[0]["source_url"] == POST["url"]
    assert facts[0]["from_image"] is True


def test_extract_drops_factless_lines(monkeypatch):
    # 숫자 없는 문장은 팩트로 쓰지 않는다 — 날조 게이트의 근거가 못 된다
    _setup(monkeypatch, '["보증보험은 유용합니다.", "보증료는 연 0.128%다."]')
    facts = image_facts.extract_facts(POST)
    assert [f["fact"] for f in facts] == ["보증료는 연 0.128%다."]


def test_extract_empty_when_no_images(monkeypatch):
    _setup(monkeypatch)
    assert image_facts.extract_facts({**POST, "image_urls": []}) == []


def test_extract_survives_download_failure(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(image_facts, "_download",
                        lambda url: (_ for _ in ()).throw(OSError("down")))
    assert image_facts.extract_facts(POST) == []


def test_extract_survives_gemini_failure(monkeypatch):
    _setup(monkeypatch)
    def boom(prompt, images, **kw):
        raise RuntimeError("gemini down")
    monkeypatch.setattr(image_facts.gemini, "generate_vision", boom)
    assert image_facts.extract_facts(POST) == []


def test_extract_skips_when_gemini_unavailable(monkeypatch):
    _setup(monkeypatch)
    monkeypatch.setattr(image_facts.gemini, "available", lambda: False)
    assert image_facts.extract_facts(POST) == []


def test_extract_handles_non_list_response(monkeypatch):
    _setup(monkeypatch, '{"facts": "wrong shape"}')
    assert image_facts.extract_facts(POST) == []


def test_download_resizes_large_image(monkeypatch):
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (2000, 3000), (120, 60, 200)).save(buf, format="PNG")
    big = buf.getvalue()
    monkeypatch.setattr(httpx, "get", lambda url, headers=None, timeout=None,
                        follow_redirects=None: httpx.Response(
                            200, content=big, request=httpx.Request("GET", url)))
    out = image_facts._download("https://x.net/big.png")
    im = Image.open(io.BytesIO(out))
    assert im.format == "JPEG"
    w, h = im.size
    assert max(w, h) <= image_facts.MAX_EDGE
    assert len(out) < len(big)
