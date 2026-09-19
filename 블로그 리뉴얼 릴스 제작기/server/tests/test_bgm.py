from core import bgm

def _setup(monkeypatch, tmp_path):
    d = tmp_path / "bgm"
    d.mkdir()
    for name in ("documentary_calm-01.mp3", "documentary_calm-02.mp3",
                 "family_warm-01.mp3"):
        (d / name).write_bytes(b"mp3")
    monkeypatch.setenv("APP_BGM_DIR", str(d))
    return d

def test_pick_mood_and_deterministic(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = bgm.pick("부동산", seed=1)
    b = bgm.pick("부동산", seed=1)
    assert a == b and a.name.startswith("documentary_calm")
    c = bgm.pick("부동산", seed=2)
    assert c.name.startswith("documentary_calm")
    assert bgm.pick("요리", seed=1).name.startswith("family_warm")

def test_pick_falls_back_to_any_then_none(monkeypatch, tmp_path):
    d = _setup(monkeypatch, tmp_path)
    # 여행 무드(emotional_daily) 없음 → 아무 mp3
    assert bgm.pick("여행", seed=1) is not None
    for f in d.iterdir():
        f.unlink()
    assert bgm.pick("부동산", seed=1) is None
