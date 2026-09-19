import json

import pytest

import config
from threads import reply_writer
from threads.models import RawPost, Verdict


@pytest.fixture
def tcfg():
    return {"interest_keywords": ["사진"], "hard_block": [],
            "landing": "https://photomagic.test", "brand": "PhotoMagic",
            "brand_desc": "사진 보정 웹서비스"}


@pytest.fixture
def tcfg_schemeless(tcfg):
    """gate.threads_config() 의 폴백 경로가 만들어내는 스킴 없는 랜딩값
    (profiles/*.yaml 의 brand.site 는 스킴을 저장하지 않는다)."""
    t = dict(tcfg)
    t["landing"] = "photomagic.test"
    return t


@pytest.fixture
def post():
    return RawPost(url="https://www.threads.net/@a/post/1", author="@a",
                   text="셀카 보정 앱 뭐 쓰세요?", posted_at="2026-08-03T10:00:00")


@pytest.fixture
def verdict():
    return Verdict(passed=True, score=88, reason="보정 고민", angle="도구 추천")


def test_validate_rejects_foreign_link(tcfg):
    bad = "저는 Midjourney 써요 https://midjourney.com 좋아요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg))


def test_validate_rejects_too_long(tcfg):
    assert any("길이" in p for p in reply_writer.validate("가" * 500, tcfg))


def test_validate_rejects_emoji_flood(tcfg):
    text = "좋아요" + "😀" * 8 + " https://photomagic.test"
    assert any("이모지" in p for p in reply_writer.validate(text, tcfg))


def test_validate_rejects_multiple_links(tcfg):
    text = "여기 https://photomagic.test 랑 https://photomagic.test/b 보세요"
    assert any("링크" in p for p in reply_writer.validate(text, tcfg))


def test_validate_rejects_unfilled_placeholder(tcfg):
    assert any("자리표시자" in p for p in reply_writer.validate("{brand} 좋아요", tcfg))


def test_validate_accepts_clean_reply(tcfg):
    good = "저도 그 고민 했어요. 배경만 정리해도 확 달라지더라고요 https://photomagic.test"
    assert reply_writer.validate(good, tcfg) == []


def test_validate_rejects_banned_phrase(tcfg, monkeypatch):
    """금칙어 가드 — 활성 프로필(현재 loan)과 무관하게 결정론적으로 검증하려고
    config.BANNED_PHRASES 를 이 테스트 안에서만 고정한다."""
    monkeypatch.setattr(config, "BANNED_PHRASES", ["무조건"])
    bad = "무조건 이거 쓰세요 https://photomagic.test"
    assert any("금칙어" in p for p in reply_writer.validate(bad, tcfg))


def test_validate_never_raises_on_none_tcfg():
    """validate() 는 '절대 예외를 던지지 않는다'는 계약이 있다 — tcfg=None 은
    아직 프로필을 못 읽은 호출자에게서 실제로 들어올 수 있다(리뷰 Round 2,
    Finding 5). 예외 대신 문제 목록으로 이어져야 하고, landing 이 없으니
    어떤 링크든 '우리 것이 아님'으로 거부되는 게 맞다."""
    problems = reply_writer.validate("아무 텍스트나 https://midjourney.com", None)
    assert isinstance(problems, list)
    assert any("주소" in p for p in problems)


# ── 도메인 소유권 판정 (리뷰 Round 1, Finding 2) ────────────────
# 부분 문자열 비교("h not in own and own not in h")는 우리 도메인이 상대
# 호스트의 부분 문자열이거나 그 반대이기만 해도 통과시켰다 — 표준적인
# 피싱 룩어라이크 모양이 전부 뚫렸다. 정확 일치/도메인 경계(.) 일치로
# 좁힌 뒤 이 세 가지 모양 + 정당한 서브도메인 1건을 확인한다.

def test_validate_rejects_lookalike_prefix_domain(tcfg):
    """own='photomagic.test' 가 상대 호스트 뒤쪽에 그대로 박혀 있어도
    (evilphotomagic.test) 우리 것이 아니다."""
    bad = "여기 써보세요 https://evilphotomagic.test 좋아요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg))


def test_validate_rejects_lookalike_suffix_domain(tcfg):
    """우리 도메인이 상대 호스트의 접두부로만 나오는 피싱형 도메인
    (photomagic.test.evil.com)."""
    bad = "여기 https://photomagic.test.evil.com 확인해보세요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg))


def test_validate_rejects_substring_owner_domain():
    """우리 도메인 자체가 상대 호스트의 부분 문자열인 경우
    (own='my-photomagic-app.test', link='app.test')."""
    tcfg2 = {"interest_keywords": [], "hard_block": [],
             "landing": "https://my-photomagic-app.test", "brand": "PhotoMagic",
             "brand_desc": "사진 보정 웹서비스"}
    bad = "여기 https://app.test 써보세요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg2))


def test_validate_accepts_legitimate_subdomain(tcfg):
    """우리 도메인의 진짜 서브도메인은 여전히 통과해야 한다(도트 경계 일치)."""
    good = "여기 https://app.photomagic.test 확인해보세요"
    assert reply_writer.validate(good, tcfg) == []


def test_write_retries_once_then_succeeds(post, verdict, tcfg):
    calls = []

    def mock(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return json.dumps({"reply": "Midjourney 쓰세요 https://midjourney.com"},
                              ensure_ascii=False)
        return json.dumps({"reply": "저도 그 고민요. https://photomagic.test"},
                          ensure_ascii=False)

    result = reply_writer.write(post, verdict, tcfg, _llm=mock)
    assert "photomagic.test" in result.text
    assert len(calls) == 2
    assert result.guard_notes, "1차 위반 내역이 남아야 한다"


def test_write_raises_after_second_violation(post, verdict, tcfg):
    mock = lambda p: json.dumps({"reply": "https://midjourney.com 최고"},
                                ensure_ascii=False)
    with pytest.raises(ValueError):
        reply_writer.write(post, verdict, tcfg, _llm=mock)


# ── 파싱 실패 시 재시도 (리뷰 Round 1, Finding 1) ────────────────
# _extract_reply() 의 ValueError 가 write() 의 재시도 루프 밖으로 새어나가
# 첫 호출이 JSON 이 아닌 응답을 뱉는 순간 2차 시도 없이 바로 죽던 회귀.

def test_write_retries_when_first_response_is_unparseable(post, verdict, tcfg):
    """1차 응답이 JSON 이 아니어도(설명 텍스트만 옴) 예외로 바로 죽지 않고
    1회 재시도해 정상 답글을 돌려준다."""
    calls = []

    def mock(prompt):
        calls.append(prompt)
        if len(calls) == 1:
            return "죄송합니다, 요청을 처리할 수 없습니다."  # JSON 아님
        return json.dumps({"reply": "저도 그 고민요. https://photomagic.test"},
                          ensure_ascii=False)

    result = reply_writer.write(post, verdict, tcfg, _llm=mock)
    assert len(calls) == 2
    assert "photomagic.test" in result.text
    assert result.guard_notes, "1차 파싱 실패 내역이 남아야 한다"


def test_write_raises_after_second_parse_failure(post, verdict, tcfg):
    """2차 시도까지 계속 JSON 이 아니면 최종적으로 ValueError 를 던진다
    (다른 예외 타입으로 새거나, 잘라낸 텍스트를 돌려주면 안 된다)."""
    mock = lambda p: "이건 계속 JSON 이 아닙니다"
    with pytest.raises(ValueError):
        reply_writer.write(post, verdict, tcfg, _llm=mock)


def test_extract_reply_error_message_is_cp949_safe():
    """LLM 원문에 cp949 로 인코딩할 수 없는 문자(em dash, 이모지)가 섞여
    JSON 파싱에 실패해도, 예외 메시지 자체는 cp949 콘솔에 그대로 찍을 수
    있어야 한다 — Task 1 에서 이 경로(원문을 그대로 예외 메시지에 실음)가
    콘솔을 죽인 사고가 있었다(리뷰 Round 1, Finding 3)."""
    garbage = "설명 — 이모지 섞임 \U0001F600 JSON 아님"
    with pytest.raises(ValueError) as exc_info:
        reply_writer._extract_reply(garbage)
    exc_info.value.args[0].encode("cp949")  # 여기서 못 뜨면 UnicodeEncodeError 로 실패


# ── reply 필드 타입 검증 (리뷰 Round 2, Finding 4) ────────────────
# {"reply": null}/숫자/리스트를 str() 로 뭉개면 'None'/'12345'/"['a', 'b']"
# 같은 문자열이 검증을 통과해 그대로 게시된다 — validate() 는 타입을 안 보므로
# 아무 가드도 안 걸린다. null 은 LLM 이 "할 말 없음"을 표현하는 충분히 있을
# 법한 방식이라 더 위험하다(조용히 실패하는 게 아니라 조용히 '성공'한 것처럼
# 보인다). 파싱 실패와 동일하게 다뤄 재시도로 흘려보내고, 두 번 다 그러면
# ValueError 로 죽어야 한다.

@pytest.mark.parametrize("bad_reply", [None, 12345, ["a", "b"]],
                         ids=["null", "number", "list"])
def test_write_retries_and_raises_on_non_string_reply(post, verdict, tcfg, bad_reply):
    calls = []

    def mock(prompt):
        calls.append(prompt)
        return json.dumps({"reply": bad_reply}, ensure_ascii=False)

    with pytest.raises(ValueError):
        reply_writer.write(post, verdict, tcfg, _llm=mock)
    assert len(calls) == 2, "타입 위반도 파싱 실패와 동일하게 1회 재시도해야 한다"


def test_extract_reply_rejects_non_string_reply_directly():
    """write() 를 거치지 않고 _extract_reply() 단독으로도 타입 위반이
    ValueError 로 드러나는지 확인(재시도 로직과 분리해서 이 가드 자체를 검증)."""
    with pytest.raises(ValueError):
        reply_writer._extract_reply(json.dumps({"reply": None}))
    with pytest.raises(ValueError):
        reply_writer._extract_reply(json.dumps({"reply": 12345}))
    with pytest.raises(ValueError):
        reply_writer._extract_reply(json.dumps({"reply": ["a", "b"]}))


# ── 스킴 없는 랜딩값 (Task 2 에서 넘어온 함정) ────────────────
# gate.threads_config() 의 폴백 경로를 타면 tcfg['landing'] 이 맨 도메인으로
# 들어올 수 있다. 그 값을 프롬프트에 그대로 박으면 LLM 이 스킴 없는 주소를
# 그대로 써서 쓰레드에서 링크로 인식되지 않을 수 있다 — 프롬프트를 만들 때
# https:// 를 붙여 정규화해야 한다.

def test_build_prompt_adds_scheme_to_bare_landing(post, verdict, tcfg_schemeless):
    prompt = reply_writer._build_prompt(post, verdict, tcfg_schemeless)
    assert "https://photomagic.test" in prompt
    # 스킴 없이 그대로 박히면 안 된다(줄 시작 등 경계에서 맨 도메인만 남는 사고 방지)
    assert "photomagic.test" not in prompt.replace("https://photomagic.test", "")


def test_write_accepts_valid_reply_with_schemeless_landing(post, verdict, tcfg_schemeless):
    mock = lambda p: json.dumps(
        {"reply": "저도 그 고민요. https://photomagic.test"}, ensure_ascii=False)
    result = reply_writer.write(post, verdict, tcfg_schemeless, _llm=mock)
    assert "photomagic.test" in result.text
    assert result.guard_notes == []


def test_validate_rejects_foreign_link_with_schemeless_landing(tcfg_schemeless):
    bad = "저는 Midjourney 써요 https://midjourney.com 좋아요"
    assert any("주소" in p for p in reply_writer.validate(bad, tcfg_schemeless))


def test_validate_accepts_clean_reply_with_schemeless_landing(tcfg_schemeless):
    good = "저도 그 고민 했어요. 배경만 정리해도 확 달라지더라고요 https://photomagic.test"
    assert reply_writer.validate(good, tcfg_schemeless) == []
