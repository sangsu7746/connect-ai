from core import image_gen, sd_webui

PNG = b"\x89PNG_fake"

def _setup_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))

def test_generate_saves_and_caches(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    calls = []
    def fake(prompt, negative, width, height):
        calls.append(prompt)
        return PNG
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", fake)
    r1 = image_gen.generate(db, "a cozy room", "isometric", "reels")
    assert not r1["cached"] and not r1["fallback"]
    assert (tmp_path / "imgs").joinpath(r1["file"]).read_bytes() == PNG
    r2 = image_gen.generate(db, "a cozy room", "isometric", "reels")
    assert r2["cached"] and r2["file"] == r1["file"]
    assert len(calls) == 1                          # 캐시 재사용 — 재호출 없음

def test_generate_style_prefix_and_negative(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    seen = {}
    def fake(prompt, negative, width, height):
        seen.update(prompt=prompt, negative=negative, width=width, height=height)
        return PNG
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", fake)
    image_gen.generate(db, "busy street", "cinematic", "long")
    assert "cinematic photography" in seen["prompt"] and "busy street" in seen["prompt"]
    assert "text" in seen["negative"]               # 공통 네거티브
    assert (seen["width"], seen["height"]) == (1024, 576)

def test_generate_fallback_on_sd_error(db, monkeypatch, tmp_path):
    _setup_dir(monkeypatch, tmp_path)
    def boom(prompt, negative, width, height):
        raise sd_webui.SDError("down")
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", boom)
    r = image_gen.generate(db, "anything", "flat_vector", "reels")
    assert r["fallback"] and r["file"]
    data = (tmp_path / "imgs").joinpath(r["file"]).read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"          # 실제 PNG 그라디언트
    # 폴백은 캐시 미등록 → SD 복구 후 재생성 가능
    assert db.execute("SELECT COUNT(*) c FROM images").fetchone()["c"] == 0

def test_gradient_card_is_png():
    data = image_gen.gradient_card("#7c3aed", 64, 128)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
