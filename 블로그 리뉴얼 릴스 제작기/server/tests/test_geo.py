from core import geo

SCENES = [
    {"idx": 0, "role": "hook", "sec": 4.1, "chapter": "", "caption": "훅"},
    {"idx": 1, "role": "summary", "sec": 3.6, "chapter": "", "caption": "요약"},
    {"idx": 2, "role": "chapter", "sec": 1.8, "chapter": "기초", "caption": "기초"},
    {"idx": 3, "role": "point", "sec": 3.0, "chapter": "기초", "caption": "p1"},
    {"idx": 4, "role": "chapter", "sec": 1.8, "chapter": "실전", "caption": "실전"},
    {"idx": 5, "role": "cta", "sec": 4.4, "chapter": "", "caption": "cta"},
]
POSTS = [{"title": "원문A", "url": "https://a/1"}]

def test_description_structure():
    d = geo.build_description(SCENES, ["기초", "실전"], POSTS,
                              ["요약 첫 줄이다.", "둘째 줄이다.", "셋째 줄이다."])
    assert d.startswith("■ 핵심 요약")
    assert "요약 첫 줄이다." in d
    assert "0:00" in d                       # 첫 챕터 타임스탬프
    assert "챕터" in d or "타임라인" in d
    assert "https://a/1" in d                # 출처

def test_timestamps_accumulate():
    d = geo.build_description(SCENES, ["기초", "실전"], POSTS, ["a.", "b.", "c."])
    # '실전' 챕터 시작 = 4.1+3.6+1.8+3.0 = 12.5 → 0:12
    assert "0:12 실전" in d
