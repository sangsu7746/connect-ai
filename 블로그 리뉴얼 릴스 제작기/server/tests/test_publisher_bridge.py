import json
import subprocess
import sys
from fastapi.testclient import TestClient
from core import publisher_bridge as pb

def test_available_requires_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(pb.settings, "publisher_dir", "")
    assert pb.available() is False
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    assert pb.available() is False              # publish_generic.py 없음
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    assert pb.available() is True

def test_publish_parses_result(monkeypatch, tmp_path):
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    def fake_run(cmd, cwd=None, capture_output=None, text=None,
                 timeout=None, encoding=None):
        class R:
            returncode = 0
            stdout = 'log line\n{"ok": true, "url": "https://blog/1", "error": ""}'
            stderr = ""
        return R()
    monkeypatch.setattr(subprocess, "run", fake_run)
    r = pb.publish("tistory", "제목", "본문")
    assert r["ok"] and r["url"] == "https://blog/1"

def test_python_prefers_publisher_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    venv_py = tmp_path / ".venv" / "Scripts" / "python.exe"
    venv_py.parent.mkdir(parents=True)
    venv_py.write_text("# stub", encoding="utf-8")
    assert pb._python() == str(venv_py)

def test_python_falls_back_without_publisher_venv(monkeypatch, tmp_path):
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    assert pb._python() == sys.executable
    monkeypatch.setattr(pb.settings, "publisher_dir", "")
    assert pb._python() == sys.executable

def test_publish_handles_timeout(monkeypatch, tmp_path):
    (tmp_path / "publish_generic.py").write_text("# stub", encoding="utf-8")
    monkeypatch.setattr(pb.settings, "publisher_dir", str(tmp_path))
    def boom(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="x", timeout=300)
    monkeypatch.setattr(subprocess, "run", boom)
    r = pb.publish("naver", "제목", "본문")
    assert not r["ok"] and "타임아웃" in r["error"]

# ── publish API (articles 라우터) ──
def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _setup(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
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
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: True)
    monkeypatch.setattr(art.article_gen, "generate_article",
                        lambda posts: {"title": "전세 보증보험 정리",
                                       "body_md": "보증료는 연 0.128% 수준이다.",
                                       "warnings": []})
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    return c, art, aid

def test_publish_endpoint_success(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: True)
    monkeypatch.setattr(art.publisher_bridge, "publish",
                        lambda platform, title, body_md, category="": {
                            "ok": True, "url": f"https://{platform}/1", "error": ""})
    r = c.post(f"/api/articles/{aid}/publish", json={"platform": "tistory"})
    assert r.status_code == 200
    got = c.get(f"/api/articles/{aid}").json()
    assert got["status"] == "published"
    assert got["published_urls"]["tistory"] == "https://tistory/1"

def test_publish_409_on_warnings_unless_force(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    c.patch(f"/api/articles/{aid}", json={"body_md": "가입자의 92%가 만족했다."})
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: True)
    monkeypatch.setattr(art.publisher_bridge, "publish",
                        lambda platform, title, body_md, category="": {
                            "ok": True, "url": "https://x/1", "error": ""})
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver"}).status_code == 409
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver", "force": True}).status_code == 200

def test_publish_503_without_bridge(monkeypatch, tmp_path):
    c, art, aid = _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(art.publisher_bridge, "available", lambda: False)
    assert c.post(f"/api/articles/{aid}/publish",
                  json={"platform": "naver"}).status_code == 503
