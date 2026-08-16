import pathlib
import subprocess
from core import renderer

SCENES = [
    {"idx": 0, "role": "hook", "sec": 4.0, "chapter": "", "caption": "훅",
     "sub": "", "narration": "", "image_prompt": "", "image_file": "a.png"},
    {"idx": 1, "role": "cta", "sec": 3.0, "chapter": "", "caption": "구독",
     "sub": "", "narration": "", "image_prompt": "", "image_file": "b.png"},
]

def _setup(monkeypatch, tmp_path):
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    from core import image_gen
    (imgs / "a.png").write_bytes(image_gen.gradient_card("#7c3aed", 64, 114))
    (imgs / "b.png").write_bytes(image_gen.gradient_card("#34d399", 64, 114))
    monkeypatch.setenv("APP_IMAGES_DIR", str(imgs))
    calls = []
    def fake_run(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        calls.append(cmd)
        # concat·클립 출력 파일을 흉내 낸다
        out = pathlib.Path(cmd[-1])
        out.write_bytes(b"fake")
        class R:
            returncode = 0
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls

def test_render_builds_expected_commands(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    out = tmp_path / "out.mp4"
    ticks = []
    renderer.render_script(SCENES, "reels", "부동산", None, out,
                           tmp_path / "work", on_scene=lambda: ticks.append(1))
    assert len(ticks) == 2                                # 씬 2개 tick
    joined = [" ".join(map(str, c)) for c in calls]
    clip_cmds = [c for c in joined if "zoompan" in c]
    assert len(clip_cmds) == 2
    assert "min(zoom+0.0011,1.16)" in clip_cmds[0]
    assert "libx264" in clip_cmds[0] and "veryfast" in clip_cmds[0]
    assert "1080x1920" in clip_cmds[0]                    # zoompan s=
    concat_cmds = [c for c in joined if "-f concat" in c]
    assert concat_cmds and "-c copy" in concat_cmds[0]
    assert out.exists()

def test_render_bgm_mux(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    bgm = tmp_path / "m.mp3"
    bgm.write_bytes(b"mp3")
    out = tmp_path / "out.mp4"
    renderer.render_script(SCENES, "reels", "부동산", bgm, out, tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    mux = [c for c in joined if "volume=0.28" in c]
    assert mux and "-stream_loop -1" in mux[0] and "-shortest" in mux[0]

def test_concat_falls_back_to_reencode(monkeypatch, tmp_path):
    calls = []
    from core import image_gen
    imgs = tmp_path / "imgs"
    imgs.mkdir()
    (imgs / "a.png").write_bytes(image_gen.gradient_card("#7c3aed", 64, 114))
    (imgs / "b.png").write_bytes(image_gen.gradient_card("#34d399", 64, 114))
    monkeypatch.setenv("APP_IMAGES_DIR", str(imgs))
    import subprocess as sp
    def fake_run(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        calls.append(cmd)
        joined = " ".join(map(str, cmd))
        class R:
            returncode = 1 if ("-f concat" in joined and "-c copy" in joined) else 0
            stderr = "copy failed"
        if R.returncode == 0:
            pathlib.Path(cmd[-1]).write_bytes(b"fake")
        return R()
    monkeypatch.setattr(sp, "run", fake_run)
    out = tmp_path / "out.mp4"
    renderer.render_script(SCENES, "reels", "부동산", None, out, tmp_path / "work")
    joined = [" ".join(map(str, c)) for c in calls]
    reenc = [c for c in joined if "-f concat" in c and "-c copy" not in c]
    assert reenc and "libx264" in reenc[0]                # 재인코딩 폴백

def test_missing_image_uses_gradient(monkeypatch, tmp_path):
    calls = _setup(monkeypatch, tmp_path)
    scenes = [dict(SCENES[0], image_file="")]              # 이미지 없음
    renderer.render_script(scenes, "reels", "부동산", None,
                           tmp_path / "o.mp4", tmp_path / "work")
    # 그라디언트 카드가 workdir에 생성돼 클립 입력으로 쓰였는지
    assert any(p.name.startswith("grad_") for p in (tmp_path / "work").iterdir())

def test_run_raises_render_error_with_stderr(monkeypatch):
    import subprocess as sp
    def boom(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        class R:
            returncode = 1
            stderr = "x" * 500
        return R()
    monkeypatch.setattr(sp, "run", boom)
    import pytest
    with pytest.raises(renderer.RenderError):
        renderer._run(["ffmpeg", "-i", "nope"])

def test_run_wraps_timeout_and_oserror(monkeypatch):
    import subprocess as sp
    import pytest
    def timeout_fn(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        raise sp.TimeoutExpired(cmd="ffmpeg", timeout=600)
    monkeypatch.setattr(sp, "run", timeout_fn)
    with pytest.raises(renderer.RenderError) as exc_info:
        renderer._run(["ffmpeg"])
    assert "시간 초과" in str(exc_info.value)
    def nf_fn(cmd, capture_output=None, text=None, timeout=None, encoding=None):
        raise FileNotFoundError("ffmpeg not found")
    monkeypatch.setattr(sp, "run", nf_fn)
    with pytest.raises(renderer.RenderError):
        renderer._run(["ffmpeg"])
