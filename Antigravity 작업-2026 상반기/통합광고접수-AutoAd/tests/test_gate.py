import json
import re
from pathlib import Path

import pytest

import config
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
    """sample_posts.json 은 Task 8 부터 {"_disclaimer": [...], "posts": [...]}
    형태다(픽스처가 synthetic 임을 밝히는 헤더를 담기 위해). 이전에는 배열
    최상위였으므로, 두 형태 모두 읽을 수 있게 해둔다."""
    payload = json.loads((FIXTURES / "sample_posts.json").read_text(encoding="utf-8"))
    data = payload["posts"] if isinstance(payload, dict) else payload
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
    LLM 이 높은 점수를 줄 여지를 아예 없애는 것이 핵심.

    프롬프트 템플릿 자체의 안내 문구(예시로 '부고' 같은 단어를 그대로 쓴다)와
    겹치지 않도록, 골든셋 글의 '본문'에서만 나오는 문구로 확인한다.
    바닥 키워드로 확인하면 템플릿 문구가 우연히 그 단어를 포함하는 순간
    이 글의 본문이 실제로 안 실렸는지와 무관하게 깨진다."""
    posts = [p for p, _ in _golden()]
    seen = {}

    def mock(prompt):
        seen["prompt"] = prompt
        return json.dumps({"results": []}, ensure_ascii=False)

    gate.screen(posts, tcfg, _llm=mock)
    assert "장례식장은 아래와 같습니다" not in seen["prompt"]   # @d, 부고
    assert "투병 중인데 사진이라도" not in seen["prompt"]       # @k, 투병(+사진 은 관심 키워드)


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


def test_threads_config_uses_profile_brand_not_active_config():
    """threads_config() 은 넘겨받은 profile 인자의 브랜드를 최우선으로 쓴다.

    config.BRAND_COMPANY/PROFILE_NAME 은 .env 의 AUTOAD_PROFILE(현재 이
    테스트 실행 시점엔 loan)로 바인딩되는 '현재 활성 프로필' 값이다. 여기로
    바로 폴백하면, 예를 들어 photomagic 프로필 딕셔너리를 넘겼는데
    화면에는 대출 상호명이 찍히는 사고가 난다(approval.py 의 profile_key
    누락 사고와 같은 유형). 이 테스트는 그 폴백이 인자보다 먼저
    쓰이지 않는지를 확인하는, threads_config() 의 첫 테스트다."""
    profile = {
        "name": "테스트업종 (가짜)",
        "brand": {"company": "테스트회사", "site": "https://test.example"},
        "threads": {},
    }
    tcfg = gate.threads_config(profile)
    assert tcfg["brand"] == "테스트회사"
    assert tcfg["brand"] != config.BRAND_COMPANY
    assert tcfg["brand_desc"] == "테스트업종 (가짜)"
    assert tcfg["landing"] == "https://test.example"


def test_malformed_score_field_does_not_crash_screen(tcfg):
    """배치 응답 자체는 유효한 JSON 이어도, 항목 하나의 score 필드가
    숫자가 아니면(예: "high") screen() 이 예외로 죽으면 안 된다.
    그 항목만 retryable 로 남기고 나머지 배치는 정상 처리돼야 한다."""
    posts = [RawPost(url="u1", author="@a", text="셀카 보정 고민"),
             RawPost(url="u2", author="@b", text="흑백 필터 추천")]
    mock = lambda p: json.dumps({"results": [
        {"index": 0, "score": "high", "reason": "?", "angle": "", "safe": True},
        {"index": 1, "score": 90, "reason": "ok", "angle": "도구 추천", "safe": True},
    ]}, ensure_ascii=False)

    verdicts = gate.screen(posts, tcfg, _llm=mock)   # 예외 없이 끝나야 한다

    assert len(verdicts) == 2
    assert verdicts[0].passed is False
    assert verdicts[0].retryable is True
    assert verdicts[1].passed is True
    assert verdicts[1].score == 90


def test_cross_batch_index_remapping(tcfg):
    """생존 글이 BATCH_SIZE 를 넘어 여러 배치로 나뉠 때, 배치 안 로컬 index 를
    원본 index 로 되돌리는 매핑이 배치가 바뀌어도 안 어긋나야 한다.

    이게 깨지면 한 글의 판정이 다른 글에 붙는다 — 하드블록 글에 광고가 붙는
    사고와 같은 유형이라 Minor 가 아니라 별도로 확인한다. 골든셋 12건으로는
    배치가 하나뿐이라(생존자 6건 < BATCH_SIZE 12) 이 회귀를 못 잡으므로
    픽스처 파일을 부풀리는 대신 글을 코드로 만든다."""
    n = gate.BATCH_SIZE * 2 + 2   # 최소 3개 배치가 나오도록
    posts = [RawPost(url=f"u{i}", author=f"@u{i}", text=f"사진 보정 고민 {i}번")
             for i in range(n)]

    def mock(prompt):
        # 프롬프트에 박힌 "[로컬index] ... N번" 에서 N(원본 index)을 읽어
        # 그 글만의 고유한 점수로 되돌려준다 — 채점 결과가 엉뚱한 글에
        # 붙으면 곧바로 어긋난 점수로 드러난다.
        results = [{"index": int(local_i), "score": int(marker),
                    "reason": "ok", "angle": "", "safe": True}
                   for local_i, marker in re.findall(r"\[(\d+)\] .*?(\d+)번", prompt)]
        return json.dumps({"results": results}, ensure_ascii=False)

    verdicts = gate.screen(posts, tcfg, _llm=mock)

    assert len(verdicts) == n
    for i, v in enumerate(verdicts):
        assert v.score == i, f"post {i} 의 점수가 다른 글의 것({v.score})으로 뒤바뀜"
