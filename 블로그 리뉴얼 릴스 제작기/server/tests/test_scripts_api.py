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
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
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
    import api.scripts as sc
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
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

def test_patch_scene_returns_gate_warnings(monkeypatch, tmp_path):
    # I1: PATCH 수동 편집은 차단하지 않되, 게이트 위반이 있으면 warnings로 동봉한다.
    # 저장 자체는 그대로 성공해야 한다.
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    r = c.patch(f"/api/scripts/{sid}/scenes/0",
                json={"narration": "가입자 92% 만족"})
    assert r.status_code == 200
    assert r.json()["warnings"]                     # 코퍼스에 없는 92 → 경고 있음
    got = c.get(f"/api/scripts/{sid}").json()
    assert got["scenes"][0]["narration"] == "가입자 92% 만족"   # 저장은 됨

def test_patch_scene_no_warnings_when_clean(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    sid = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                       "fmt": "reels", "duration": 30}).json()["id"]
    r = c.patch(f"/api/scripts/{sid}/scenes/0", json={"caption": "수정 자막"})
    assert r.json()["warnings"] == []

def test_create_503_without_gemini_key(monkeypatch, tmp_path):
    # I2-①: 키 없이 진입하면 명확한 503 — 퇴화 대본을 만들지 않는다.
    c = make_client(monkeypatch, tmp_path)
    import api.scripts as sc
    monkeypatch.setattr(sc.gemini, "available", lambda: False)
    ids = _seed_posts(c, monkeypatch)
    r = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                     "fmt": "reels", "duration": 30})
    assert r.status_code == 503

def test_create_502_when_generation_totally_fails(monkeypatch, tmp_path):
    # I2-②: generate_script가 GeminiError를 던지면(모든 배치 실패) 502로 변환된다.
    c = make_client(monkeypatch, tmp_path)
    import api.scripts as sc
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
    ids = _seed_posts(c, monkeypatch)
    def boom(posts, fmt, duration):
        raise sc.gemini.GeminiError("대본 생성 실패 — 모든 배치 호출이 실패했습니다")
    monkeypatch.setattr(sc.script_gen, "generate_script", boom)
    r = c.post("/api/scripts", json={"category_id": 1, "post_ids": ids,
                                     "fmt": "reels", "duration": 30})
    assert r.status_code == 502

def test_create_404_on_bad_category(monkeypatch, tmp_path):
    # I4: 존재하지 않는 category_id는 posts 로드(비싼 크롤·진단)보다 먼저 404로 막는다.
    c = make_client(monkeypatch, tmp_path)
    import api.scripts as sc
    monkeypatch.setattr(sc.gemini, "available", lambda: True)
    r = c.post("/api/scripts", json={"category_id": 999, "post_ids": [1],
                                     "fmt": "reels", "duration": 30})
    assert r.status_code == 404
