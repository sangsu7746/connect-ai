# -*- coding: utf-8 -*-
"""SD 백엔드 — 강제 네거티브와 흰 배경 게이트.

2026-09-08 스파이크 실측:
 · DreamShaper_8 은 인물 편향이 강하다. "노트북 화면" 을 요구했는데 인물 사진이
   나왔다 → 인물 금지 네거티브를 코드가 강제 주입해야 한다.
 · pure white background 를 넣고 photo background 를 네거티브에 넣어도
   4장 중 1장이 사진 배경으로 나왔다 → 프롬프트가 아니라 게이트로 확인한다.
"""
import sys
from pathlib import Path

from PIL import Image

BASE = Path(__file__).parent.parent
sys.path.insert(0, str(BASE))

from content import sd_backend as S


def test_neg_force_bans_people_and_text():
    for word in ("person", "woman", "face", "hands",
                 "text", "korean text", "watermark", "logo"):
        assert word in S.NEG_FORCE


def test_build_prompt_always_appends_neg_force(monkeypatch):
    """모델이 인물 금지를 빠뜨려도 코드가 붙인다."""
    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "a cat",
                                             "negative_prompt": "blurry"})
    out = S.build_prompt("고양이 스티커", 768, 768)
    assert out["prompt"] == "a cat"
    assert "blurry" in out["negative_prompt"]
    assert "person" in out["negative_prompt"]      # 강제 주입 확인


def test_is_clean_white_accepts_white_border():
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(60, 140):
        for y in range(60, 140):
            img.putpixel((x, y), (10, 20, 30))     # 가운데만 그림
    assert S.is_clean_white(img) is True


def test_is_clean_white_rejects_photo_background():
    """스파이크의 수채 타일 사례 — 종이·팔레트가 찍힌 사진 배경."""
    img = Image.new("RGB", (200, 200), (120, 130, 110))
    assert S.is_clean_white(img) is False


def test_is_clean_white_rejects_dark_corners():
    """showcase._gen_one 주석이 경고한 비네트."""
    img = Image.new("RGB", (200, 200), (255, 255, 255))
    for x in range(0, 30):
        for y in range(0, 30):
            img.putpixel((x, y), (20, 20, 20))
    assert S.is_clean_white(img) is False


def test_gen_tile_retries_until_gate_passes(monkeypatch):
    bad = Image.new("RGB", (64, 64), (100, 100, 100))
    good = Image.new("RGB", (64, 64), (255, 255, 255))
    calls = {"n": 0}

    def fake_txt2img(prompt, negative, width, height):
        calls["n"] += 1
        return bad if calls["n"] == 1 else good

    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "p", "negative_prompt": "n"})
    monkeypatch.setattr(S, "txt2img", fake_txt2img)
    out = S.gen_tile("브리프", size=64, retries=2)
    assert calls["n"] == 2
    assert S.is_clean_white(out) is True


def test_gen_tile_gives_up_after_retries(monkeypatch):
    bad = Image.new("RGB", (64, 64), (100, 100, 100))
    monkeypatch.setattr(S, "_ask_llm",
                        lambda brief, w, h: {"prompt": "p", "negative_prompt": "n"})
    monkeypatch.setattr(S, "txt2img", lambda *a, **k: bad)
    import pytest
    with pytest.raises(RuntimeError, match="흰 배경"):
        S.gen_tile("브리프", size=64, retries=2)
