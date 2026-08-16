import json
import time
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))
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
            s["image_prompt"] = "cozy room"
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

def test_images_job_fills_scenes(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: b"\x89PNG_x")
    jid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    j = _wait_job(c, jid)
    assert j["status"] == "done" and j["progress"] == j["total"] == 7
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert all(s["image_file"] for s in scenes)
    assert not any(s["image_fallback"] for s in scenes)

def test_images_job_skips_existing_unless_force(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    calls = []
    def fake(p, n, w, h):
        calls.append(p)
        return b"\x89PNG_x"
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", fake)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    n1 = len(calls)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    assert len(calls) == n1                    # 전부 채워져 있어 스킵
    _wait_job(c, c.post(f"/api/scripts/{sid}/images",
                        json={"force": True}).json()["job_id"])
    assert len(calls) > n1                     # force는 재생성

def test_images_job_fallback_marks_scene(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    from core import sd_webui
    def boom(p, n, w, h):
        raise sd_webui.SDError("down")
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", boom)
    j = _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    assert j["status"] == "done"               # 폴백이라 잡은 성공
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert all(s["image_fallback"] for s in scenes)

def test_single_scene_regen(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img",
                        lambda p, n, w, h: b"\x89PNG_y")
    r = c.post(f"/api/scripts/{sid}/scenes/0/image").json()
    assert r["image_file"]
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert scenes[0]["image_file"] == r["image_file"]

def test_job_404(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    assert c.get("/api/jobs/999").status_code == 404
