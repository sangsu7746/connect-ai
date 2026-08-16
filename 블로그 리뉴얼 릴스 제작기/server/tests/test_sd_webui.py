import base64
import httpx
import pytest
from core import sd_webui

PNG_STUB = b"\x89PNG\r\n\x1a\n_stub"

def test_txt2img_decodes_base64(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    captured = {}
    def fake_post(url, json=None, timeout=None):
        captured.update(json)
        assert url.endswith("/sdapi/v1/txt2img")
        body = {"images": [base64.b64encode(PNG_STUB).decode()]}
        return httpx.Response(200, json=body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = sd_webui.txt2img("a cat", "bad", 576, 1024)
    assert out == PNG_STUB
    assert captured["steps"] == 25 and captured["cfg_scale"] == 7
    assert captured["sampler_name"] == "DPM++ 2M Karras"
    assert captured["width"] == 576 and captured["height"] == 1024

def test_txt2img_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None:
                        httpx.Response(500, json={}, request=httpx.Request("POST", url)))
    with pytest.raises(sd_webui.SDError):
        sd_webui.txt2img("a", "b", 576, 1024)

def test_txt2img_raises_on_empty_images(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "post", lambda url, json=None, timeout=None:
                        httpx.Response(200, json={"images": []},
                                       request=httpx.Request("POST", url)))
    with pytest.raises(sd_webui.SDError):
        sd_webui.txt2img("a", "b", 576, 1024)

def test_available(monkeypatch):
    monkeypatch.setattr(sd_webui.settings, "sd_webui_url", "http://x:7860")
    monkeypatch.setattr(httpx, "get", lambda url, timeout=None:
                        httpx.Response(200, json=[], request=httpx.Request("GET", url)))
    assert sd_webui.available() is True
    def boom(url, timeout=None):
        raise OSError("down")
    monkeypatch.setattr(httpx, "get", boom)
    assert sd_webui.available() is False
