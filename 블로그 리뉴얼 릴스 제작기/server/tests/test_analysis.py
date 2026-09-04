from core import analysis

POSTS = [
    {"title": "전세 보증보험 총정리", "url": "https://a/1",
     "content": "보증료는 연 0.128%다.\n숫자 없는 줄.\n한도는 7억원이다."},
    {"title": "보증보험 가입법", "url": "https://a/2",
     "content": "보증료는 연 0.128%다.\n서류는 3가지다."},
]

def test_fact_sheet_numeric_lines_only_dedup():
    facts = analysis.build_fact_sheet(POSTS)
    texts = [f["fact"] for f in facts]
    assert "보증료는 연 0.128%다." in texts
    assert "숫자 없는 줄." not in texts
    assert texts.count("보증료는 연 0.128%다.") == 1        # 중복 제거
    assert all(f["source_url"] for f in facts)

def test_corpus_text_joins_all():
    c = analysis.corpus_text(POSTS)
    assert "0.128%" in c and "서류는 3가지다" in c

def test_extract_chapters_uses_gemini(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate",
                        lambda p, **kw: '["기초", "가입 절차", "주의점"]')
    assert analysis.extract_chapters(POSTS, 3) == ["기초", "가입 절차", "주의점"]

def test_extract_chapters_fallback_without_gemini(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: False)
    ch = analysis.extract_chapters(POSTS, 2)
    assert len(ch) == 2 and all(isinstance(c, str) and c for c in ch)

def test_extract_chapters_pads_short_answer(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate", lambda p, **kw: '["하나"]')
    assert len(analysis.extract_chapters(POSTS, 3)) == 3

def test_extract_chapters_non_list_json_falls_back(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate",
                        lambda p, **kw: '{"chapters": ["기초", "실전"]}')
    ch = analysis.extract_chapters(POSTS, 2)
    assert len(ch) == 2
    assert "chapters" not in ch          # dict 키 순회 오염이 아니어야 함

def test_extract_chapters_gates_titles(monkeypatch):
    monkeypatch.setattr(analysis.gemini, "available", lambda: True)
    monkeypatch.setattr(analysis.gemini, "generate",
                        lambda p, **kw: '["월 92만원 버는 법", "가입 절차"]')
    ch = analysis.extract_chapters(POSTS, 2)
    assert len(ch) == 2 and "가입 절차" in ch
    assert all("92" not in c for c in ch)      # 코퍼스에 없는 숫자 타이틀 교체됨


IMG_POSTS = [
    {"title": "보증보험 정리", "url": "https://a/1",
     "content": "본문 텍스트에는 숫자가 없다.",
     "image_facts": [{"fact": "보증료는 연 0.128%다.", "source_title": "보증보험 정리",
                      "source_url": "https://a/1", "from_image": True}]},
]


def test_fact_sheet_merges_image_facts():
    facts = analysis.build_fact_sheet(IMG_POSTS)
    texts = [f["fact"] for f in facts]
    assert "보증료는 연 0.128%다." in texts
    img = [f for f in facts if f.get("from_image")]
    assert len(img) == 1


def test_corpus_includes_image_facts_for_gate():
    """이미지에서 읽은 숫자를 대본에 썼는데 게이트가 막으면 모순이다 —
    corpus(게이트의 유일한 근거)에 이미지 팩트도 들어가야 한다."""
    corpus = analysis.corpus_text(IMG_POSTS)
    assert "0.128" in corpus

    from core import guardrails
    r = guardrails.check("보증료는 연 0.128% 수준이다.", corpus)
    assert r["ok"], r["blocking"]


def test_corpus_without_image_facts_unchanged():
    plain = [{"title": "t", "url": "u", "content": "보증료는 연 0.128%다."}]
    assert "0.128" in analysis.corpus_text(plain)
