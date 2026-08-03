import pytest

import config
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
# 아래부터는 브리프의 Step 1 밖에서 추가한 테스트다. 디스패치 지시대로
# "가드 하나마다 일부러 부수고 → 실패 확인 → 원복" 을 셀렉터·CAPTCHA·
# 회수(delete_reply)·예외 안전성·인간형 타이핑까지 넓혀서 검증한다.
# 실브라우저는 절대 안 띄운다 — _FakeDriver/_FakeAutomator 로 대역한다
# (tests/test_harvester.py 의 기존 관례와 같은 패턴).
# ============================================================


class _FakeElement:
    def __init__(self, href=None):
        self._href = href
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
    """selenium 없이 _do_reply()/delete_reply() 의 분기만 확인하기 위한 대역.
    find_elements() 는 (by, selector) 조합이 아니라 selector 문자열만으로
    찾는다 — publisher.py 안의 셀렉터 문자열이 CSS/XPath 사이에서 겹치지
    않기 때문에 이 정도 단순화로 충분하다."""

    def __init__(self, page_source="", elements=None):
        self.page_source = page_source
        self._elements = elements or {}
        self.get_calls = []

    def get(self, url):
        self.get_calls.append(url)

    def find_elements(self, by, selector):
        return self._elements.get(selector, [])


class _FakeAutomator:
    def __init__(self, driver):
        self.driver = driver
        self.quit_called = False

    def quit(self):
        self.quit_called = True


BOX_SEL = "div[contenteditable='true'], textarea"
PERM_SEL = "a[href*='/post/']"
MORE_SEL = "svg[aria-label*='더'], [aria-label*='More']"
DELETE_XPATH = "//*[text()='삭제' or text()='Delete']"


@pytest.fixture
def no_sleep(monkeypatch):
    """_do_reply()/delete_reply() 안의 time.sleep() 을 무력화해 테스트를
    즉시 끝낸다 — 실제 대기 시간이 필요한 건 실브라우저를 다룰 때뿐이고,
    가드/분기 검증에는 의미가 없다."""
    import threads.publisher as pubmod
    monkeypatch.setattr(pubmod.time, "sleep", lambda *_a, **_k: None)


def _attach_fake(pub, page_source="", elements=None):
    pub._auto = _FakeAutomator(_FakeDriver(page_source=page_source, elements=elements))
    return pub._auto.driver


# ── CAPTCHA/차단 화면 감지 ──────────────────────────────────────
def test_captcha_screen_blocks_and_stops_immediately(pub, no_sleep):
    """캡차 화면이면 blocked=True 로 즉시 멈추고, 입력창을 찾으려는
    시도조차 하지 않는다(재시도 금지가 핵심이므로 '더 진행하지 않았다'
    까지 같이 확인한다). 메시지엔 마스터 스위치를 끄라는 안내가 있어야
    한다(디스패치의 모호성 해소 지시)."""
    driver = _attach_fake(pub, page_source="<html>Unusual Activity Detected</html>",
                          elements={BOX_SEL: [_FakeElement()]})
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True and r.ok is False
    assert "THREADS_ENABLED" in r.error
    # 입력창을 찾았다면 그 element 의 click_calls 가 남았을 것 — 캡차
    # 감지 후 더 진행하지 않았다면 애초에 접근하지 않는다.
    box = driver._elements[BOX_SEL][0]
    assert box.click_calls == 0


def test_korean_block_phrase_also_detected(pub, no_sleep):
    """영문 문구만 잡으면 실제 한국어 차단 화면을 놓친다 — 별도로 확인."""
    _attach_fake(pub, page_source="<html>일시적으로 차단된 계정입니다</html>")
    r = pub.reply("https://www.threads.net/@a/post/1", "hi", dry_run=False)
    assert r.blocked is True


# ── 셀렉터 소실 = error, blocked 아님(하드룰 확인) ──────────────
def test_missing_input_box_is_error_not_blocked(pub, no_sleep):
    """입력창 셀렉터가 안 잡히는 건 안전장치가 막은 게 아니라 진짜
    고장(UI 변경)이다 — blocked=False, ok=False 로 갈려야 운영자가
    엉뚱하게 '한도 초과'로 오인하지 않는다."""
    _attach_fake(pub, page_source="<html>ok</html>", elements={})
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
    _attach_fake(pub, page_source="<html>ok</html>",
                elements={BOX_SEL: [box], PERM_SEL: [perm]})
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
    _attach_fake(pub, page_source="<html>ok</html>",
                elements={BOX_SEL: [box], PERM_SEL: []})
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
    브리프 원안은 _do_reply() 만 try 로 감쌌지만, _rate_ok() 도 db 를
    조회하므로 DB 오류가 나면 여기서도 예외가 새어나갈 수 있었다 —
    reply() 전체(가드 판정~발행)를 감싸도록 넓힌 이유. 이건 안전장치가
    막은 게 아니라 진짜 고장이므로 blocked=False 여야 한다."""
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
    driver = _attach_fake(pub, page_source="<html>ok</html>", elements={
        MORE_SEL: [more_btn],
    })
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
    _attach_fake(pub, page_source="<html>ok</html>")
    ok = pub.delete_reply("https://www.threads.net/@a/post/1", dry_run=False)
    assert ok is False


def test_delete_reply_invalid_url_returns_false(pub):
    ok = pub.delete_reply("https://facebook.com/groups/1", dry_run=False)
    assert ok is False
    assert pub._auto is None


# ── _cp949_safe 재사용 확인(콘솔 출력 내용이 아니라 '호출됐는지'만
#    검증한다 — 콘솔 출력 자체를 assert 하지 말라는 지시를 지킨다) ──
def test_dry_run_reply_text_goes_through_cp949_safe(pub, monkeypatch):
    import threads.publisher as pubmod
    seen = []
    orig = pubmod._cp949_safe

    def spy(s):
        seen.append(s)
        return orig(s)
    monkeypatch.setattr(pubmod, "_cp949_safe", spy)
    pub.reply("https://www.threads.net/@a/post/1", "안녕하세요", dry_run=True)
    assert "안녕하세요" in seen
