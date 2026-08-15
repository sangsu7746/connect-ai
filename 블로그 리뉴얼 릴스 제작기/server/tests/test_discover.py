from fastapi.testclient import TestClient

NAVER_ITEMS = [
    {"source": "naver", "title": "전세 보증보험 총정리", "url": "https://blog.naver.com/a/1",
     "summary": "보증료 연 0.128%", "blogger": "b1", "posted_at": "20260810"},
    {"source": "naver", "title": "전세 보증보험 가입방법", "url": "https://blog.naver.com/a/2",
     "summary": "", "blogger": "b2", "posted_at": "20260809"},
]
GOOGLE_ITEMS = [
    {"source": "google", "title": "전세 보증보험 비용 후기", "url": "https://x.tistory.com/3",
     "summary": "3억 기준 38만원", "blogger": "", "posted_at": ""},
]

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    import api.discover as disc
    monkeypatch.setattr(disc.naver, "search_blog", lambda q, display=10: NAVER_ITEMS)
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: GOOGLE_ITEMS)
    monkeypatch.setattr(disc.crawler, "fetch_content",
                        lambda url: "본문. 보증료 연 0.128%입니다.\n1. 서류\n2. 신청\n3. 납부")
    return TestClient(main.app)

def test_discover_stores_and_diagnoses(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    r = c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert r.status_code == 200
    posts = c.get("/api/categories/1/posts").json()
    assert len(posts) == 3
    assert all(p["score"] is not None for p in posts)
    assert posts == sorted(posts, key=lambda p: -p["score"])

def test_discover_idempotent_by_url(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert len(c.get("/api/categories/1/posts").json()) == 3   # URL UNIQUE upsert

def test_source_filter(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert {p["source"] for p in
            c.get("/api/categories/1/posts?source=google").json()} == {"google"}

def test_google_playwright_fallback_when_no_cse(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    import api.discover as disc
    monkeypatch.setattr(disc.google_search, "search_blog", lambda q, num=10: [])
    monkeypatch.setattr(disc.google_search, "available", lambda: False)
    monkeypatch.setattr(disc.google_search, "search_blog_playwright",
                        lambda q, num=10: GOOGLE_ITEMS)
    c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert any(p["source"] == "google"
               for p in c.get("/api/categories/1/posts").json())

def test_discover_survives_naver_failure(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    import api.discover as disc
    def boom(q, display=10):
        raise OSError("naver down")
    monkeypatch.setattr(disc.naver, "search_blog", boom)
    r = c.post("/api/categories/1/discover", json={"keyword": "전세 보증보험"})
    assert r.status_code == 200                       # 구글만으로 진행
    posts = c.get("/api/categories/1/posts").json()
    assert {p["source"] for p in posts} == {"google"}
