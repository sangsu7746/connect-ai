from fastapi.testclient import TestClient

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def test_seed_categories_exist(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    cats = c.get("/api/categories").json()
    assert len(cats) == 6
    assert {"부동산", "재테크", "건강", "요리", "여행", "IT"} == {x["name"] for x in cats}
    assert all(len(x["keywords"]) == 5 for x in cats)

def test_add_delete_category_and_keyword(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    r = c.post("/api/categories", json={"name": "육아", "emoji": "🍼"})
    cid = r.json()["id"]
    c.post(f"/api/categories/{cid}/keywords", json={"keyword": "이유식"})
    cats = {x["name"]: x for x in c.get("/api/categories").json()}
    assert cats["육아"]["keywords"] == ["이유식"]
    c.delete(f"/api/categories/{cid}/keywords/이유식")
    c.delete(f"/api/categories/{cid}")
    assert "육아" not in {x["name"] for x in c.get("/api/categories").json()}
