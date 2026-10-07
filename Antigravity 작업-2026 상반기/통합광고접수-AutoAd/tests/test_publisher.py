import pytest

import config
from channels.base import PostResult
from threads.publisher import ThreadsPublisher


@pytest.fixture
def pub(monkeypatch):
    monkeypatch.setattr(config, "THREADS_ENABLED", True)
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", False)
    monkeypatch.setattr(config, "THREADS_DAILY_LIMIT", 20)
    monkeypatch.setattr(config, "THREADS_AUTO_DAILY_LIMIT", 3)
    p = ThreadsPublisher(account="tester")
    p._logged_in = True
    return p


def test_dry_run_never_touches_browser(pub):
    r = pub.reply("https://www.threads.net/@a/post/1", "안녕하세요", dry_run=True)
    assert r.ok is True and r.dry_run is True


def test_invalid_url_is_blocked_not_error(pub):
    r = pub.reply("https://facebook.com/groups/1", "hi", dry_run=False)
    assert r.blocked is True and r.ok is False


def test_master_switch_blocks(pub, monkeypatch):
    monkeypatch.setattr(config, "THREADS_ENABLED", False)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "THREADS_ENABLED" in r.error


def test_global_dry_run_blocks(pub, monkeypatch):
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", True)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "GLOBAL_DRY_RUN" in r.error


def test_not_logged_in_is_blocked(pub):
    pub._logged_in = False
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert "로그인" in r.error


def test_total_limit_blocks(pub, monkeypatch):
    monkeypatch.setattr("db.threads_replies_today", lambda auto_only=False: 20)
    assert pub._rate_ok() is False
    assert "총 상한" in pub._rate_reason()


def test_auto_limit_blocks_independently(pub, monkeypatch):
    """총 상한엔 여유가 있어도 자동분 상한이 차면 자동 발행은 막힌다.
    이게 gate 오작동 시 사고 크기를 묶는 장치다."""
    def counts(auto_only=False):
        return 3 if auto_only else 5
    monkeypatch.setattr("db.threads_replies_today", counts)
    assert pub._rate_ok(auto=False) is True
    assert pub._rate_ok(auto=True) is False
    assert "자동 발행 상한" in pub._rate_reason(auto=True)


# ============================================================
# 아래부터는 브리프의 Step 1 밖에서 추가한 테스트다. 실브라우저는 절대
# 안 띄운다 — _FakeDriver/_FakeAutomator 로 대역한다(tests/test_
# harvester.py 의 기존 관례와 같은 패턴). 셀렉터 문자열은 publisher.py
# 의 모듈 상수를 직접 참조해 중복 하드코딩으로 인한 드리프트를 막는다
# (리뷰 라운드 1 지적 반영).
# ============================================================
import threads.publisher as pubmod  # noqa: E402  (상수 참조용)

BOX_SEL = pubmod._BOX_SELECTOR
PERM_SEL = pubmod._PERM_SELECTOR
MORE_SEL = pubmod._MORE_SELECTOR
DELETE_XPATH = pubmod._DELETE_XPATH


class _FakeElement:
    def __init__(self, href=None, text=None):
        self._href = href
        self.text = text
        self.click_calls = 0
        self.send_keys_calls = []

    def click(self):
        self.click_calls += 1

    def send_keys(self, *args):
        self.send_keys_calls.append(args)

    def get_attribute(self, name):
        if name == "href":
            return self._href
        return None


class _FakeDriver:
    """selenium 없이 _do_reply()/delete_reply() 의 분기만 확인하기 위한
    대역. find_elements() 는 (by, selector) 조합이 아니라 selector
    문자열만으로 찾는다 — publisher.py 안의 셀렉터 문자열이 CSS/XPath
    사이에서 겹치지 않기 때문에 이 정도 단순화로 충분하다.

    리뷰 Finding 1 대응: current_url(챌린지 리다이렉트 흉내)과
    find_element("body").text(화면에 보이는 텍스트만 흉내, page_source
    와 분리)를 추가했다 — 번들 스크립트(page_source)와 실제 보이는
    본문(body.text)이 다를 수 있다는 걸 테스트에서 표현하기 위함."""

    def __init__(self, page_source="", elements=None,
                 current_url="https://www.threads.net/@a/post/1",
                 body_text=None):
        self.page_source = page_source
        self._elements = elements or {}
        self.current_url = current_url
        self._body_text = body_text
        self.get_calls = []

    def get(self, url):
        self.get_calls.append(url)

    def find_elements(self, by, selector):
        return self._elements.get(selector, [])

    def find_element(self, by, value):
        # 실제 selenium 은 못 찾으면 NoSuchElementException 을 던진다 —
        # 여기서는 "body_text 를 안 줬다" = "그 요소가 없다"로 흉내낸다.
        if self._body_text is None:
            raise RuntimeError("no such element(가짜)")
        return _FakeElement(text=self._body_text)


class _FakeAutomator:
    def __init__(self, driver):
        self.driver = driver
        self.quit_called = False

    def quit(self):
        self.quit_called = True


@pytest.fixture
def no_sleep(monkeypatch):
    """_do_reply()/delete_reply() 안의 time.sleep() 을 무력화해 테스트를
    즉시 끝낸다 — 실제 대기 시간이 필요한 건 실브라우저를 다룰 때뿐이고,
    가드/분기 검증에는 의미가 없다."""
    monkeypatch.setattr(pubmod.time, "sleep", lambda *_a, **_k: None)


def _attach_fake(pub, page_source="", elements=None,
                 current_url="https://www.threads.net/@a/post/1",
                 body_text=None):
    pub._auto = _FakeAutomator(_FakeDriver(
        page_source=page_source, elements=elements,
        current_url=current_url, body_text=body_text))
    return pub._auto.driver


# ── 셀렉터 소실 = error, blocked 아님(하드룰 확인) ──────────────
def test_missing_input_box_is_error_not_blocked(pub, no_sleep):
    """입력창 셀렉터가 안 잡히고 화면 텍스트도(찾을 수 없어) 캡차 문구가
    없으면, 안전장치가 막은 게 아니라 진짜 고장(UI 변경)이다 —
    blocked=False, ok=False 로 갈려야 운영자가 엉뚱하게 '한도 초과'로
    오인하지 않는다."""
    _attach_fake(pub, elements={})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.ok is False
    assert r.blocked is False


# ── 성공 경로: 인간형 타이핑 + 퍼머링크 확보 ────────────────────
def test_successful_reply_types_one_char_at_a_time(pub, no_sleep):
    """한 번에 붙여넣지 않는다 — send_keys 호출 횟수가 문자 수만큼
    나뉘어 있어야 인간형 타이핑이다(붙여넣기면 호출이 1번으로 뭉친다)."""
    text = "안녕하세요 광고입니다"
    box = _FakeElement()
    perm = _FakeElement(href="https://www.threads.net/@tester/post/NEW1")
    _attach_fake(pub, elements={BOX_SEL: [box], PERM_SEL: [perm]})
    r = pub.reply("https://www.threads.net/@a/post/1", text, dry_run=False)
    assert r.ok is True
    assert r.blocked is False
    # 마지막 한 번은 Ctrl+Enter 제출이므로 문자 수 + 1 이어야 한다.
    assert len(box.send_keys_calls) == len(text) + 1
    typed_chars = [c[0] for c in box.send_keys_calls[:-1]]
    assert "".join(typed_chars) == text
    assert r.perm_url == "https://www.threads.net/@tester/post/NEW1"


def test_successful_reply_without_findable_permalink_is_still_ok(pub, no_sleep):
    """퍼머링크를 못 찾아도 답글 자체는 이미 나갔을 수 있다 — ok=True 를
    유지하고 error 에만 사유를 남긴다(실패로 보고하면 운영자가 중복
    발행을 시도하게 된다는 게 디스패치의 명시적 지시)."""
    box = _FakeElement()
    _attach_fake(pub, elements={BOX_SEL: [box], PERM_SEL: []})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.ok is True
    assert r.perm_url is None
    assert r.error  # 사유는 남아 있어야 한다(주소 확인 실패)


# ── reply() 는 절대 예외를 던지지 않는다 ────────────────────────
def test_unexpected_exception_becomes_error_result_not_raised(pub, no_sleep):
    """드라이버 쪽에서 예상 못 한 예외(RuntimeError 등)가 나도 reply() 는
    그걸 삼키고 PostResult 로만 알려야 한다 — 이건 '안전장치가 막은 것'이
    아니라 진짜 고장이므로 blocked=False 여야 한다."""
    class _ExplodingDriver(_FakeDriver):
        def get(self, url):
            raise RuntimeError("네트워크 끊김(가짜)")
    pub._auto = _FakeAutomator(_ExplodingDriver())
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.ok is False
    assert r.blocked is False
    assert "RuntimeError" in r.error


def test_rate_check_db_failure_is_error_not_blocked(pub, monkeypatch):
    """가드 판정 자체(db 조회)가 죽는 경우도 reply() 는 삼켜야 한다.
    reply() 전체(가드 판정~발행)를 감싸는 이유. 이건 안전장치가 막은
    게 아니라 진짜 고장이므로 blocked=False 여야 한다."""
    def boom(auto_only=False):
        raise RuntimeError("DB 잠김(가짜)")
    monkeypatch.setattr("db.threads_replies_today", boom)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.ok is False
    assert r.blocked is False
    assert "RuntimeError" in r.error


# ── delete_reply(): 마스터 스위치가 꺼져 있어도 회수는 동작해야 한다 ──
def test_delete_reply_dry_run_never_touches_browser(pub):
    ok = pub.delete_reply("https://www.threads.net/@a/post/1", dry_run=True)
    assert ok is True
    assert pub._auto is None  # 브라우저를 만들지도 않았다


def test_delete_reply_works_even_when_master_switch_is_off(pub, monkeypatch, no_sleep):
    """THREADS_ENABLED=0(마스터 스위치 꺼짐)이어도 회수는 막히면 안
    된다 — 마스터 스위치를 끈 바로 그 순간이 회수가 가장 필요한
    상황이기 때문이다(디스패치의 핵심 모호성 해소 지시)."""
    monkeypatch.setattr(config, "THREADS_ENABLED", False)
    monkeypatch.setattr(config, "GLOBAL_DRY_RUN", True)
    more_btn = _FakeElement()
    delete_item = _FakeElement()
    confirm_btn = _FakeElement()
    driver = _attach_fake(pub, elements={MORE_SEL: [more_btn]})
    # XPath 클릭 두 번(메뉴 항목 클릭 → 확인 클릭)이 같은 selector 를
    # 쓰므로, find_elements 를 클릭 횟수에 따라 다르게 주도록 patch 한다.
    calls = {"n": 0}
    orig_find = driver.find_elements

    def find_elements(by, selector):
        if selector == DELETE_XPATH:
            calls["n"] += 1
            return [delete_item] if calls["n"] == 1 else [confirm_btn]
        return orig_find(by, selector)
    driver.find_elements = find_elements

    ok = pub.delete_reply("https://www.threads.net/@a/post/1", dry_run=False)
    assert ok is True
    assert more_btn.click_calls == 1
    assert delete_item.click_calls == 1
    assert confirm_btn.click_calls == 1


def test_delete_reply_blocked_by_login_state_only(pub, no_sleep):
    """로그인 안 된 상태면 회수도 못 한다 — 이건 마스터 스위치와 무관한
    별개의 전제조건이다."""
    pub._logged_in = False
    _attach_fake(pub)
    ok = pub.delete_reply("https://www.threads.net/@a/post/1", dry_run=False)
    assert ok is False


def test_delete_reply_invalid_url_returns_false(pub):
    ok = pub.delete_reply("https://facebook.com/groups/1", dry_run=False)
    assert ok is False
    assert pub._auto is None


# ── _cp949_safe 재사용 확인(콘솔 출력 내용이 아니라 '호출됐는지'만
#    검증한다 — 콘솔 출력 자체를 assert 하지 말라는 지시를 지킨다) ──
def test_dry_run_reply_text_goes_through_cp949_safe(pub, monkeypatch):
    seen = []
    orig = pubmod._cp949_safe

    def spy(s):
        seen.append(s)
        return orig(s)
    monkeypatch.setattr(pubmod, "_cp949_safe", spy)
    pub.reply("https://www.threads.net/@a/post/1", "안녕하세요", dry_run=True)
    assert "안녕하세요" in seen


# ============================================================
# 리뷰 라운드 1 Finding 1 — CAPTCHA 오탐으로 기능 전체가 조용히
# 멈추는 사고. page_source(번들 스크립트 포함) 문구 매칭을 버리고
# (1) URL 리다이렉트 (2) 화면에 보이는 텍스트 + 입력창 부재 co-occur
# 로 바꿨다. 4가지 필수 시나리오 + 한국어 문구 변형을 전부 확인한다.
# ============================================================
def test_challenge_url_redirect_blocks_without_touching_composer(pub, no_sleep):
    """탐지 1순위: URL 자체가 챌린지 경로로 리다이렉트되면 입력창이
    있어도 손대지 않고 즉시 막는다(재시도 금지가 핵심이므로 '더 진행
    안 했다'까지 같이 확인). 메시지엔 마스터 스위치를 끄라는 안내가
    있어야 한다(디스패치의 모호성 해소 지시)."""
    box = _FakeElement()
    _attach_fake(pub, current_url="https://www.threads.net/challenge/?next=/",
                elements={BOX_SEL: [box]})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True and r.ok is False
    assert "THREADS_ENABLED" in r.error
    assert box.click_calls == 0


def test_checkpoint_url_redirect_also_detected(pub, no_sleep):
    _attach_fake(pub, current_url="https://www.threads.net/accounts/suspended/")
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True


def test_bundled_script_captcha_mention_does_not_cause_false_block(pub, no_sleep):
    """리뷰 Finding 1 재현 사례 1 — 입력창이 마침 안 잡힌 순간에도(진짜
    셀렉터 변경일 수도 있는 상황) page_source(번들 스크립트 포함)에
    'captcha'/'unusual activity' 가 있다는 이유만으로 캡차로 오판하면
    안 된다. 화면에 실제로 보이는 텍스트(body_text)는 깨끗하므로 이건
    '셀렉터 변경'(error) 이지 캡차(blocked) 가 아니다 — page_source
    전체를 문구 매칭하면 정상 페이지의 봇탐지 스크립트 참조 하나로
    기능이 통째로 죽는 사고(리뷰 지적)를 재현·방지 확인. 입력창을
    일부러 비워서(elements={}) 코드가 실제로 문구 매칭 분기를 타게
    한다 — 입력창이 있으면 co-occurrence 게이트에서 걸러져 이 분기
    자체를 안 타므로(별도 테스트로 검증) page_source 대 visible text
    구분을 제대로 확인하지 못한다."""
    _attach_fake(pub,
                page_source="<script>window.__recaptcha_site_key='xxx';"
                            "reportUnusualActivity();</script>",
                body_text="오늘 날씨가 좋네요",
                elements={})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is False
    assert r.ok is False  # 입력창은 실제로 없다 — 성공은 아니지만 '캡차'로 오판하지도 않는다


def test_author_post_text_saying_captcha_does_not_block(pub, no_sleep):
    """리뷰 Finding 1 재현 사례 2 — 글쓴이 본문에 우연히 'captcha' 라는
    단어가 있어도(잡담 등) 입력창이 정상이면 차단이 아니다. 남이 쓴
    글 내용으로 우리 계정이 스스로를 막아버리는 사고를 막는다."""
    box = _FakeElement()
    perm = _FakeElement(href="https://www.threads.net/@tester/post/NEW1")
    _attach_fake(pub,
                body_text="오늘 캡차(captcha) 때문에 시간 다 썼어요. "
                          "unusual activity 라는 말도 웃기더라",
                elements={BOX_SEL: [box], PERM_SEL: [perm]})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is False
    assert r.ok is True


def test_real_challenge_screen_without_composer_blocks(pub, no_sleep):
    """진짜 차단 화면 재현 — 입력창이 없고(구조적 신호) 화면 문구도
    캡차 관련이면(내용 신호) 두 조건이 같이 나올 때만 막는다."""
    _attach_fake(pub, body_text="Please complete this captcha to continue",
                elements={})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert r.ok is False


def test_korean_block_phrase_with_no_composer_blocks(pub, no_sleep):
    """영문 문구만 잡으면 실제 한국어 차단 화면을 놓친다 — 별도로
    확인(입력창 부재와 co-occur 하는 경로도 같이 검증)."""
    _attach_fake(pub, body_text="일시적으로 차단된 계정입니다", elements={})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True


# ============================================================
# 리뷰 라운드 1 Finding 2 — post_url/reply_url 이 str 이 아니면(int·
# float·None) 형식검증이 try 밖에서 TypeError 를 그대로 던졌다.
# reply()/delete_reply() 둘 다 어떤 값이 와도 raise 없이 결과를
# 돌려줘야 한다.
# ============================================================
@pytest.mark.parametrize("bad_target", [12345, 3.14, None])
def test_reply_with_non_string_target_never_raises(pub, bad_target):
    r = pub.reply(bad_target, "hi", dry_run=False)
    assert isinstance(r, PostResult)
    assert r.ok is False
    assert r.blocked is True  # 형식이 잘못된 대상 = 의도된 차단


@pytest.mark.parametrize("bad_target", [12345, 3.14, None])
def test_delete_reply_with_non_string_target_never_raises(pub, bad_target):
    ok = pub.delete_reply(bad_target, dry_run=False)
    assert ok is False


# ============================================================
# 리뷰 라운드 1 Finding 3 — _rate_ok()/_rate_reason() 을 따로 불러
# db 를 두 번 왕복하면, 그 사이 카운트가 바뀔 때 blocked=True 인데
# error="" 인 설명 안 되는 결과가 나올 수 있었다. reply() 는 이제
# 한 번의 스냅샷(_rate_status)만 쓴다.
# ============================================================
def test_rate_limit_check_does_not_double_query_db(pub, monkeypatch):
    """reply() 가 상한 판정에서 db.threads_replies_today() 를 한 번만
    부르는지 직접 센다(이전엔 _rate_ok()+_rate_reason() 두 번 호출로
    두 번 왕복했다)."""
    calls = {"n": 0}

    def counting(auto_only=False):
        calls["n"] += 1
        return 20  # THREADS_DAILY_LIMIT(20)과 같음 → 총 상한 도달
    monkeypatch.setattr("db.threads_replies_today", counting)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert r.error
    assert calls["n"] == 1


def test_rate_reason_matches_the_snapshot_that_blocked(pub, monkeypatch):
    """카운트가 조회 사이에 바뀌는 상황을 흉내낸다 — 예전 방식(판정
    따로, 사유 따로 조회)이라면 첫 조회는 20(상한 도달)이어도 두 번째
    조회 때 19(정상)로 바뀌어 있으면 blocked=True 인데 error="" 가
    나오는 레이스가 있었다. 지금은 한 번의 스냅샷만 쓰므로 이런 값이
    나올 수 없다."""
    counts = iter([20, 19, 19, 19])

    def flaky(auto_only=False):
        return next(counts, 19)
    monkeypatch.setattr("db.threads_replies_today", flaky)
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True
    assert r.error  # 반드시 사유가 있어야 한다(빈 문자열 금지)
    assert "총 상한" in r.error


# ============================================================
# 리뷰 라운드 1 Finding 4 — 문자당 타이핑 간격이 고정값(20ms)이면
# 그 자체가 균일성이라는 탐지 신호가 된다. 무작위 범위로 바꿨다.
# ============================================================
def test_typing_interval_has_jitter(pub, monkeypatch):
    """문자당 간격이 완전히 균일하면 그 자체가 탐지 신호다 — sleep
    인자를 스파이로 잡아 타이핑 구간(고정 sleep 값인 3·0.5·1·4 보다
    훨씬 작은 값들)만 골라 최소 두 가지 값 이상 나오는지 확인한다
    (운 나쁘게 전부 같은 값이 나올 확률은 사실상 0에 가깝다)."""
    delays = []
    monkeypatch.setattr(pubmod.time, "sleep", lambda s: delays.append(s))
    box = _FakeElement()
    perm = _FakeElement(href="https://www.threads.net/@tester/post/NEW1")
    _attach_fake(pub, elements={BOX_SEL: [box], PERM_SEL: [perm]})
    text = "abcdefghij"
    r = pub.reply("https://www.threads.net/@a/post/1", text, dry_run=False)
    assert r.ok is True
    # 고정 sleep(3, 0.5, 1, 4)보다 뚜렷하게 작은 값만 타이핑 구간이다
    # (_TYPE_DELAY_MAX = 0.06 이므로 0.1 미만으로 걸러도 안전하다).
    typing_delays = [d for d in delays if d < 0.1]
    assert len(typing_delays) == len(text)
    assert len(set(round(d, 6) for d in typing_delays)) >= 2
