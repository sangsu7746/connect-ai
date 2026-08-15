import httpx
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
