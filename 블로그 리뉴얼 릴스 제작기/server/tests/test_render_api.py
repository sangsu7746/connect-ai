import time
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))
    monkeypatch.setenv("APP_VIDEOS_DIR", str(tmp_path / "vids"))
    monkeypatch.setenv("APP_BGM_DIR", str(tmp_path / "bgm"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _make_script(c, monkeypatch):
    import api.discover as disc
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: [
        {"source": "naver", "title": "전세 보증보험 총정리",
         "url": "https://blog.naver.com/a/1", "summary": "",
         "blogger": "b", "posted_at": "20260810"}])
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세"})
    ids = [p["id"] for p in c.get("/api/categories/1/posts").json()]
    import api.scripts as sc
    from core import storyboard
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
    def fake_generate(posts, fmt, duration):
        scenes = storyboard.build_scenes(fmt, duration, [])
        for s in scenes:
            s["caption"] = "자막"
            s["narration"] = "나레이션"
        return {"scenes": scenes, "fact_sheet": [], "chapters": [],
                "diag": {"score": 2, "verdict": "회색 소", "answers": [],
                         "hooks": [], "weak": []}}
    monkeypatch.setattr(sc.script_gen, "generate_script", fake_generate)
    return c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                        "fmt": "reels", "duration": 30}).json()["id"]

def _wait_job(c, jid, timeout=10):
    for _ in range(timeout * 20):
        j = c.get(f"/api/jobs/{jid}").json()
        if j["status"] != "running":
            return j
        time.sleep(0.05)
    raise TimeoutError

def test_render_job_creates_record(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    def fake_render(scenes, fmt, category, bgm_path, out_path, workdir,
                    on_scene=None):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"mp4")
        for _ in scenes:
            if on_scene:
                on_scene()
    monkeypatch.setattr(rd.renderer, "render_script", fake_render)
    jid = c.post(f"/api/scripts/{sid}/render").json()["job_id"]
    j = _wait_job(c, jid)
    assert j["status"] == "done"
    renders = c.get(f"/api/scripts/{sid}/renders").json()
    assert len(renders) == 1 and renders[0]["file"].endswith(".mp4")
    assert renders[0]["duration_sec"] == 30

def test_render_conflicts_with_image_job(monkeypatch, tmp_path):
    import threading
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    gate = threading.Event()
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: (gate.wait(timeout=5), b"\x89PNG")[1])
    ijid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    try:
        assert c.post(f"/api/scripts/{sid}/render").status_code == 409
    finally:
        gate.set()
    _wait_job(c, ijid)

def test_render_error_marks_job(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.render as rd
    from core.renderer import RenderError
    def boom(*a, **kw):
        raise RenderError("ffmpeg 실패")
    monkeypatch.setattr(rd.renderer, "render_script", boom)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/render").json()["job_id"])
    assert j["status"] == "error" and "ffmpeg" in j["error"]
    assert c.get(f"/api/scripts/{sid}/renders").json() == []
