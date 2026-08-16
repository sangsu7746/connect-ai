import io
from PIL import Image
from core import captions

def _img(data: bytes) -> Image.Image:
    return Image.open(io.BytesIO(data))

def test_png_rgba_frame_size():
    data = captions.render_caption("자막 테스트", "보조 자막", "point", 540, 960)
    img = _img(data)
    assert img.mode == "RGBA" and img.size == (540, 960)

def test_point_text_in_lower_third_with_scrim():
    data = captions.render_caption("하단 자막", "", "point", 540, 960)
    img = _img(data)
    alpha = img.split()[3]
    # 상단 1/3에는 불투명 픽셀이 없어야, 하단 1/3에는 있어야 한다
    top = alpha.crop((0, 0, 540, 320))
    bottom = alpha.crop((0, 640, 540, 960))
    assert max(top.getextrema()) == (0, 0) or top.getextrema()[1] == 0
    assert bottom.getextrema()[1] > 0

def test_hook_text_centered():
    data = captions.render_caption("중앙 훅", "", "hook", 540, 960)
    alpha = _img(data).split()[3]
    middle = alpha.crop((0, 320, 540, 640))
    assert middle.getextrema()[1] > 0

def test_empty_caption_returns_fully_transparent():
    data = captions.render_caption("", "", "point", 540, 960)
    alpha = _img(data).split()[3]
    assert alpha.getextrema() == (0, 0)

def test_font_fallback(monkeypatch):
    monkeypatch.setattr(captions, "FONT_CANDIDATES", ["Z:/no/such/font.ttf"])
    data = captions.render_caption("폴백", "", "cta", 540, 960)
    assert _img(data).size == (540, 960)          # 기본 폰트로도 동작
