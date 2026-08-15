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
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: True)
    monkeypatch.setattr(art.article_gen, "generate_article",
                        lambda posts: {"title": "전세 보증보험 핵심 정리",
                                       "body_md": "■ 핵심 요약\n- 보증료는 연 0.128%다.",
                                       "warnings": []})
    return art

def test_create_get_list(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    got = c.get(f"/api/articles/{aid}").json()
    assert got["title"].startswith("전세") and got["status"] == "draft"
    assert [a["id"] for a in c.get("/api/categories/1/articles").json()] == [aid]

def test_patch_regates(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    _mock_engine(monkeypatch)
    aid = c.post("/api/articles",
                 json={"category_id": 1, "post_ids": ids}).json()["id"]
    r = c.patch(f"/api/articles/{aid}",
                json={"body_md": "가입자의 92%가 만족했다."}).json()
    assert r["warnings"]                       # 날조 숫자 경고 동봉(저장은 됨)
    assert c.get(f"/api/articles/{aid}").json()["body_md"].startswith("가입자")

def test_create_503_without_gemini(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    ids = _seed_posts(c, monkeypatch)
    import api.articles as art
    monkeypatch.setattr(art.gemini, "available", lambda: False)
    assert c.post("/api/articles",
                  json={"category_id": 1, "post_ids": ids}).status_code == 503

def test_create_404_bad_category(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    _mock_engine(monkeypatch)
    assert c.post("/api/articles",
                  json={"category_id": 9999, "post_ids": [1]}).status_code == 404
