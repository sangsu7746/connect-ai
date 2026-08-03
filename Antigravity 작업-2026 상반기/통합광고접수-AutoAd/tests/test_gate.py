import json
from pathlib import Path

import pytest

from threads import gate
from threads.models import RawPost

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def tcfg():
    return {
        "interest_keywords": ["사진", "셀카", "보정", "인생네컷", "증명사진",
                              "포토샵", "필터", "화질", "흑백", "프로필사진"],
        "hard_block": ["부고", "삼가", "사고", "확진", "투병", "정당", "사망"],
        "landing": "https://example.test",
        "brand": "PhotoMagic",
    }


def _golden():
    data = json.loads((FIXTURES / "sample_posts.json").read_text(encoding="utf-8"))
    return [(RawPost(url=d["url"], author=d["author"], text=d["text"],
                     posted_at=d["posted_at"]), d["label"]) for d in data]


def test_hardblock_beats_interest(tcfg):
    """관심 키워드가 있어도 하드블록이 이긴다. 이게 뒤집히면 부고 글에 광고가 붙는다."""
    ok, reason = gate.keyword_pass("어제 사고 사진 보정해서 올려도 되나요", tcfg)
    assert ok is False
    assert "사고" in reason


def test_keyword_pass_needs_interest(tcfg):
    assert gate.keyword_pass("오늘 점심 뭐 먹지", tcfg)[0] is False
    assert gate.keyword_pass("셀카 보정 앱 추천좀", tcfg)[0] is True


def test_screen_returns_same_length_and_order(tcfg):
    posts = [p for p, _ in _golden()]
    mock = lambda prompt: json.dumps({"results": [
        {"index": i, "score": 80, "reason": "ok", "angle": "도구 추천", "safe": True}
        for i in range(len(posts))]}, ensure_ascii=False)
    verdicts = gate.screen(posts, tcfg, _llm=mock)
    assert len(verdicts) == len(posts)


def test_hardblocked_posts_never_reach_llm(tcfg):
    """하드블록 글이 LLM 까지 가면 안 된다 — 비용도 낭비지만
    LLM 이 높은 점수를 줄 여지를 아예 없애는 것이 핵심."""
    posts = [p for p, _ in _golden()]
    seen = {}

    def mock(prompt):
        seen["prompt"] = prompt
        return json.dumps({"results": []}, ensure_ascii=False)

    gate.screen(posts, tcfg, _llm=mock)
    assert "부고" not in seen["prompt"]
    assert "투병" not in seen["prompt"]


def test_llm_failure_is_retryable_not_rejection(tcfg):
    """LLM 이 쓰레기를 뱉어도 예외로 죽지 않는다. 그리고 그 글들은
    '부적합'이 아니라 '아직 모름'(retryable)이어야 한다 —
    할당량이 떨어진 회차의 수집분을 영영 버리지 않기 위해."""
    posts = [p for p, _ in _golden()]
    verdicts = gate.screen(posts, tcfg, _llm=lambda p: "이건 JSON 이 아님")
    assert all(v.passed is False for v in verdicts)
    # 키워드에서 이미 떨어진 글은 retryable 이 아니다(재판정해도 결과가 같다)
    llm_stage = [v for v in verdicts if "LLM" in v.reason]
    assert llm_stage and all(v.retryable for v in llm_stage)


def test_keyword_rejection_is_not_retryable(tcfg):
    posts = [RawPost(url="u", author="@a", text="오늘 점심 뭐 먹지")]
    assert gate.screen(posts, tcfg, _llm=lambda p: "")[0].retryable is False


def test_unsafe_flag_forces_fail(tcfg):
    """LLM 이 safe=False 를 주면 점수가 높아도 떨어뜨린다."""
    posts = [RawPost(url="u", author="@a", text="셀카 보정 고민")]
    mock = lambda p: json.dumps({"results": [
        {"index": 0, "score": 99, "reason": "민감", "angle": "", "safe": False}]},
        ensure_ascii=False)
    assert gate.screen(posts, tcfg, _llm=mock)[0].passed is False
