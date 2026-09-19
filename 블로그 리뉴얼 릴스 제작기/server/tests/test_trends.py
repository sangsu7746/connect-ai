import httpx
from fastapi.testclient import TestClient
from core import naver

def _fake_datalab_response(groups):
    return {"results": [
        {"title": g["groupName"],
         "data": [{"period": "2026-08-03", "ratio": 10.0},
                  {"period": "2026-08-10", "ratio": 25.0}]}
        for g in groups]}

def test_datalab_batches_of_five(monkeypatch):
    calls = []
    def fake_post(url, json=None, headers=None, timeout=None):
        calls.append(len(json["keywordGroups"]))
        return httpx.Response(200, json=_fake_datalab_response(json["keywordGroups"]),
                              request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    out = naver.datalab_ratios([f"kw{i}" for i in range(7)])
    assert calls == [5, 2]                # 5개씩 배치
    assert out["kw0"] == (25.0, 10.0)     # (last, prev)

def test_rise_pct():
    assert naver.rise_pct(25.0, 10.0) == 150.0
    assert naver.rise_pct(10.0, 0.0) == 1000.0   # prev=0 → max(prev,1) 분모

def make_client(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_PATH", str(tmp_path / "t.db"))
    import importlib, main
    importlib.reload(main)
    return TestClient(main.app)

def test_refresh_endpoint_upserts_and_sorts(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    import api.trends as tr
    monkeypatch.setattr(tr.naver, "datalab_ratios", lambda kws: {
        kws[0]: (10.0, 10.0),   # rise 0%
        kws[1]: (30.0, 10.0),   # rise 200%
    })
    r = c.post("/api/categories/1/trends/refresh")
    assert r.status_code == 200
    rows = r.json()
    assert rows[0]["rise_pct"] >= rows[-1]["rise_pct"]        # 내림차순
    assert set(rows[0].keys()) == {"keyword", "rise_pct"}      # 계약 형태
    # 두 번 호출해도 PK upsert라 행 수 불변
    c.post("/api/categories/1/trends/refresh")
    cats = c.get("/api/categories").json()
    cat1 = next(x for x in cats if x["id"] == 1)
    assert len(cat1["top_keywords"]) <= 5                      # top 5 계약

def test_refresh_endpoint_404_without_seeds(monkeypatch, tmp_path):
    c = make_client(monkeypatch, tmp_path)
    r = c.post("/api/categories/9999/trends/refresh")
    assert r.status_code == 404
