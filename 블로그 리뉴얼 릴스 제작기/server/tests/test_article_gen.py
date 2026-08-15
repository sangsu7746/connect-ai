import json
from core import article_gen

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1", "source": "naver",
     "summary": "",
     "content": "보증료는 연 0.128%다.\n3억이면 연 38만원이다.\n"
                "하지만 사실 집주인 동의는 필요 없다.\n1. 서류\n2. 신청\n3. 납부"},
]

GOOD_MD = ("■ 핵심 요약\n- 전세 보증보험 보증료는 연 0.128%다.\n"
           "- 3억 전세면 연 38만원 수준이다.\n- 집주인 동의 없이 가입된다.\n\n"
           "## 보증료 계산\n전세 보증보험 보증료는 연 0.128%로 확인됐다.\n\n"
           "## 가입 절차\n전세 보증보험 가입은 서류 준비부터 시작한다.\n\n"
           "## 주의할 점\n전세 보증보험이 맞지 않는 경우도 있다.\n\n"
           "## 마무리\n전세 보증보험 조건은 원문에서 확인하자.")

def _gen_ok(prompt, **kw):
    return json.dumps({"title": "전세 보증보험 핵심 정리",
                       "body_md": GOOD_MD}, ensure_ascii=False)

def test_generate_article_ok(monkeypatch):
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate", _gen_ok)
    out = article_gen.generate_article(POSTS)
    assert out["title"] == "전세 보증보험 핵심 정리" and len(out["title"]) <= 32
    assert out["body_md"].startswith("■ 핵심 요약")
    assert out["warnings"] == []

def test_fabricated_paragraph_dropped(monkeypatch):
    bad_md = GOOD_MD + "\n\n## 추가\n가입자의 92%가 만족했다."
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "전세 보증보험 핵심 정리", "body_md": bad_md},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert "92" not in out["body_md"]          # 재생성도 같은 응답 → 문단 삭제
    assert out["warnings"]                     # 삭제 사실이 경고로 남음

def test_copied_paragraph_dropped(monkeypatch):
    bad_md = GOOD_MD + "\n\n## 복사\n하지만 사실 집주인 동의는 필요 없다."
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "전세 보증보험 핵심 정리", "body_md": bad_md},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert "하지만 사실 집주인 동의는 필요 없다" not in out["body_md"]

def test_title_truncated_and_gated(monkeypatch):
    monkeypatch.setattr(article_gen.gemini, "available", lambda: True)
    monkeypatch.setattr(article_gen.gemini, "generate",
                        lambda p, **kw: json.dumps(
                            {"title": "역대급 최저가 " + "가" * 40, "body_md": GOOD_MD},
                            ensure_ascii=False))
    out = article_gen.generate_article(POSTS)
    assert len(out["title"]) <= 32
    assert "역대급" not in out["title"]        # 금지어 제목 → 안전 제목으로 교체
    assert out["warnings"]

def test_gate_article_reusable():
    probs = article_gen.gate_article("제목", "가입자의 92%가 만족했다.",
                                     "본문 숫자 없음", ["본문 숫자 없음"])
    assert probs and any("92" in p for p in probs)

def test_unavailable_raises(monkeypatch):
    import pytest
    from core.gemini import GeminiError
    monkeypatch.setattr(article_gen.gemini, "available", lambda: False)
    with pytest.raises(GeminiError):
        article_gen.generate_article(POSTS)
