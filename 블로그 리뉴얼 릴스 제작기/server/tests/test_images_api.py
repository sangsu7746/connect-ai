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

def test_job_preserves_concurrent_text_edit(monkeypatch, tmp_path):
    """C1 회귀 — 이미지 잡이 도는 동안 사용자가 PATCH로 자막을 고쳐도
    잡이 마지막에 scenes 전체를 스냅샷째로 되쓰면서 그 편집을 지워버리면 안 된다.
    씬별 fresh-read/merge 구조라면 편집이 그대로 살아남는다."""
    import threading
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    gate = threading.Event()
    first_done = threading.Event()
    n = {"count": 0}
    def slow(p, ng, w, h):
        n["count"] += 1
        if n["count"] == 1:
            first_done.set()
        else:
            gate.wait(timeout=5)
        return b"\x89PNG_x"
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", slow)
    jid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    assert first_done.wait(timeout=5)
    c.patch(f"/api/scripts/{sid}/scenes/0", json={"caption": "잡 중 수정"})
    gate.set()
    _wait_job(c, jid)
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert scenes[0]["caption"] == "잡 중 수정"        # 편집 보존
    assert all(s["image_file"] for s in scenes)        # 이미지도 전부

def test_images_job_refills_fallback_without_force(monkeypatch, tmp_path):
    """I5 — SD가 다운돼 전부 폴백으로 채워진 뒤 SD가 복구되면, force 없는
    일반 잡도 폴백 씬을 재충전해야 한다(이미 image_file이 있다고 스킵하면 안 됨)."""
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    from core import sd_webui
    def boom(p, n, w, h):
        raise sd_webui.SDError("down")
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", boom)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert all(s["image_fallback"] for s in scenes)

    def fixed(p, n, w, h):
        return b"\x89PNG_x"
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", fixed)
    _wait_job(c, c.post(f"/api/scripts/{sid}/images").json()["job_id"])
    scenes = c.get(f"/api/scripts/{sid}").json()["scenes"]
    assert not any(s["image_fallback"] for s in scenes)

def test_concurrent_jobs_rejected(monkeypatch, tmp_path):
    import threading
    c = make_client(monkeypatch, tmp_path)
    sid = _make_script(c, monkeypatch)
    import api.images as im
    gate = threading.Event()
    def slow(p, n, w, h):
        gate.wait(timeout=5)
        return b"\x89PNG_x"
    monkeypatch.setattr(im.image_gen.sd_webui, "txt2img", slow)
    jid = c.post(f"/api/scripts/{sid}/images").json()["job_id"]
    try:
        assert c.post(f"/api/scripts/{sid}/images").status_code == 409
        assert c.post(f"/api/scripts/{sid}/scenes/0/image").status_code == 409
    finally:
        gate.set()
    j = _wait_job(c, jid)
    assert j["status"] == "done"

def test_orphaned_running_job_marked_error_on_restart(monkeypatch, tmp_path):
    """C2 — 서버가 running 잡 도중 죽으면 그 행은 영원히 running으로 남아
    has_running()이 계속 409를 반환한다. 재시작(main 모듈 재로드) 시
    남아있는 running 잡을 error로 정리해야 한다."""
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setenv("APP_IMAGES_DIR", str(tmp_path / "imgs"))
    import importlib, main
    importlib.reload(main)
    from core.db import get_conn
    conn = get_conn()
    conn.execute(
        "INSERT INTO jobs(kind, status, ref, created_at) VALUES('images','running','1','x')")
    conn.commit()
    conn.close()

    importlib.reload(main)  # 서버 재시작 시뮬레이션

    conn = get_conn()
    row = conn.execute("SELECT status, error FROM jobs WHERE ref='1'").fetchone()
    conn.close()
    assert row["status"] == "error"
    assert row["error"]
