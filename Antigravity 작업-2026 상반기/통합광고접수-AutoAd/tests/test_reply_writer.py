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
