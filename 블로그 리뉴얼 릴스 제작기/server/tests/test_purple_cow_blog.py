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
