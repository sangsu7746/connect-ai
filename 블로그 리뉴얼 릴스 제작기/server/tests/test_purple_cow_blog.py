from core import purple_cow_blog as pc

RICH = {"title": "전세 보증보험 가입 총정리", "source": "naver", "summary": "",
        "content": ("전세 보증보험은 보증료가 연 0.128%입니다. 3억 전세면 연 38만원."
                    "\n하지만 사실 집주인 동의는 필요 없습니다. 잘못 알려진 상식이죠."
                    "\n가입 방법\n1. 서류 준비\n2. 앱 신청\n3. 보증료 납부"
                    "\n체크리스트를 꼭 확인하세요.")}
POOR = {"title": "오늘의 일기", "source": "naver", "summary": "",
        "content": "오늘은 날씨가 좋았다. 산책을 했다."}
CORPUS = [
    {"title": "전세 보증보험 가입방법 정리", "source": "naver"},
    {"title": "전세 보증보험 비용 후기", "source": "google"},
    {"title": "고양이 간식 추천", "source": "naver"},
]

def test_rich_post_scores_high():
    d = pc.diagnose(RICH, CORPUS)
    assert d["score"] == 4
    assert d["verdict"] == "보랏빛 소"
    assert len(d["answers"]) == 4
    assert d["hooks"]                       # 훅 후보 존재
    assert any("0.128%" in h for h in d["hooks"])

def test_poor_post_scores_zero():
    d = pc.diagnose(POOR, [])
    assert d["score"] == 0
    assert d["verdict"] == "완전한 갈색 소"

def test_both_source_bonus():
    # 유사 글 1개뿐이어도 네이버+구글 양쪽 노출이면 no_discount YES (spec §5 가점)
    post = {"title": "파킹통장 금리 비교", "source": "naver", "summary": "", "content": ""}
    corpus = [{"title": "파킹통장 금리 총정리", "source": "google"}]
    d = pc.diagnose(post, corpus)
    nd = next(a for a in d["answers"] if a["key"] == "no_discount")
    assert nd["yes"] is True

def test_extract_numbers():
    nums = pc.extract_numbers("연 0.128%이고 3억이며 38만원, 2026년")
    units = [u for _, _, u in nums]
    assert "%" in units and "억" in units and "만원" in units

def test_evidence_only_from_data():
    # 진단 근거는 반드시 원문 부분 문자열 (LLM 추론 금지 원칙)
    d = pc.diagnose(RICH, CORPUS)
    for a in d["answers"]:
        if a["yes"] and a["key"] != "no_discount":
            assert a["evidence"] in (RICH["content"] + RICH["title"] + RICH["summary"])

def test_hooks_deduplicated():
    d = pc.diagnose(RICH, CORPUS)
    assert len(d["hooks"]) == len(set(d["hooks"]))

def test_weak_lists_failed_questions():
    d = pc.diagnose(POOR, [])
    assert len(d["weak"]) == 4
    d2 = pc.diagnose(RICH, CORPUS)
    assert d2["weak"] == []

def test_admin_numbers_excluded_from_hooks():
    # 훅 단위(만원)가 있어도 행정 문맥 줄이면 배제 — 필터 실경로 검증
    post = {"title": "보증보험 안내", "source": "naver", "summary": "",
            "content": "문의 전화 상담료는 3만원입니다"}
    assert pc.diagnose(post, [])["hooks"] == []
    # 양성 대조: 행정 문맥 없으면 같은 단위 숫자가 훅이 된다
    post2 = {"title": "보증보험 안내", "source": "naver", "summary": "",
             "content": "보증료는 연 38만원이다"}
    assert pc.diagnose(post2, [])["hooks"]

def test_range_and_negative_numbers_not_admin_blocked():
    post = {"title": "시세 정리", "source": "naver", "summary": "",
            "content": "이 지역 원룸 시세는 1000-5000만원 선이고 전월 대비 15% 내렸다"}
    assert pc.diagnose(post, [])["hooks"]      # 하이픈 구간·퍼센트는 훅 유지

def test_pick_principles_mapping():
    d = pc.diagnose(POOR, [])        # 전 문항 실패 → 1,2,5,6,7,8 + 3,4 → 상위 5
    ns = [p["n"] for p in pc._pick_principles(d)]
    assert ns == [1, 2, 5, 6, 7]
    d2 = pc.diagnose(RICH, CORPUS)   # 3점 이상 → 덜어내기 [3,4,6]
    assert [p["n"] for p in pc._pick_principles(d2)] == [3, 4, 6]

def test_build_script_guide_scene_level_scope():
    d = pc.diagnose(RICH, CORPUS)
    full = pc.build_script_guide(d, scene_level=False)
    one = pc.build_script_guide(d, scene_level=True)
    assert "[씬 구성]" in full and "[이번 출력 범위]" not in full
    assert "[이번 출력 범위]" in one and "[씬 구성]" not in one
    assert "금지" in full and str(d["score"]) in full
