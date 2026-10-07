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

def test_generate_salt_not_in_prompt_but_changes_key(db, monkeypatch, tmp_path):
    """I6 — 리트라이 솔트는 캐시 키에만 반영돼야 한다. SD로 나가는 prompt에
    솔트 문자열이 섞이면 안 되고(그림 품질과 무관한 노이즈), 대신 솔트가
    다르면 캐시 파일명(=해시 키)이 달라져서 강제 재생성 시 새 이미지를 받는다."""
    _setup_dir(monkeypatch, tmp_path)
    seen = []
    def fake(prompt, negative, width, height):
        seen.append(prompt)
        return PNG
    monkeypatch.setattr(image_gen.sd_webui, "txt2img", fake)
    r1 = image_gen.generate(db, "a cozy room", "isometric", "reels", salt="abc123")
    assert "abc123" not in seen[0]
    r2 = image_gen.generate(db, "a cozy room", "isometric", "reels", salt="def456")
    assert "def456" not in seen[1]
    assert seen[0] == seen[1]                        # 프롬프트 자체는 솔트와 무관하게 동일
    assert r1["file"] != r2["file"]                   # 솔트 다르면 캐시 키(파일명)도 다름

def test_gradient_card_is_png():
    data = image_gen.gradient_card("#7c3aed", 64, 128)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
