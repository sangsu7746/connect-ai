import json
from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def _seed_posts(c, monkeypatch):
    import api.discover as disc
    items = [{"source": "naver", "title": "전세 보증보험 총정리",
              "url": "https://blog.naver.com/a/1", "summary": "보증료 0.128%",
              "blogger": "b", "posted_at": "20260810"}]
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: items)
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: True)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "보증료는 연 0.128%다.\n3억이면 연 38만원이다.")
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    return [p["id"] for p in c.get("/api/categories/1/posts").json()]

def _mock_engine(monkeypatch):
    import api.scripts as sc
    def fake_generate(posts, fmt, duration):
        from core import storyboard
        scenes = storyboard.build_scenes(fmt, duration, ["기초", "실전"])
        for s in scenes:
            if s["role"] != "chapter":
                s["caption"] = "보증료 0.128%"
                s["narration"] = "보증료는 연 0.128%입니다"
        return {"scenes": scenes, "fact_sheet": [], "chapters": ["기초", "실전"],
                "diag": {"score": 2, "verdict": "회색 소", "answers": [],
                         "hooks": [], "weak": []}}
    monkeypatch.setattr(sc.script_gen, "generate_script", fake_generate)
    return sc

def test_create_get_and_list(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    r = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                     "fmt": "long", "duration": 60})
    sid = r.json()["id"]
    got = c.get(f"/api/scripts/{sid}").json()
    assert len(got["scenes"]) == 10 and got["description_md"].startswith("■")
    lst = c.get("/api/categories/1/scripts").json()
    assert [s["id"] for s in lst] == [sid]

def test_patch_scene(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    r = c.patch(f"/api/scripts/{sid}/scenes/0", json={"caption": "수정 자막"})
    assert r.json()["caption"] == "수정 자막"
    assert c.get(f"/api/scripts/{sid}").json()["scenes"][0]["caption"] == "수정 자막"

def test_regen_scene_endpoint(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    sc = _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    monkeypatch.setattr(sc.script_gen, "regen_scene",
                        lambda scene, posts, diag: {**scene, "caption": "재생성됨"})
    r = c.post(f"/api/scripts/{sid}/scenes/0/regen")
    assert r.json()["caption"] == "재생성됨"

def test_create_404_on_bad_posts(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    assert c.post("/api/scripts", json={"category_id": 1, "post_ids": [999],
                                        "fmt": "reels", "duration": 30}).status_code == 404

def test_patch_truncates_caption_and_sub(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    r = c.patch(f"/api/scripts/{sid}/scenes/0",
                json={"caption": "가" * 30, "sub": "나" * 30})
    assert len(r.json()["caption"]) == 18 and len(r.json()["sub"]) == 22
