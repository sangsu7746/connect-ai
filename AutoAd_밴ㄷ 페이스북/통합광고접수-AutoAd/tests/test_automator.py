# ============================================================
#  tests/test_automator.py — ThreadsAutomator 의 예외-안전성 회귀
#  (리뷰 Round 1 Finding 1·4)
#  · 실브라우저를 절대 띄우지 않는다. selenium 이 필요한 지점(start())은
#    호출하지 않고, .driver 에 가짜 객체를 직접 꽂아 넣어 그 다음
#    단계(save_cookies/load_session)의 예외 처리만 겨눈다.
# ============================================================
from threads.automator import ThreadsAutomator


class _RaisingCookieDriver:
    """WebDriverException 대역 — 사람이 2FA·캡차를 오래 붙잡고 있다가
    세션이 끊긴 상태에서 get_cookies() 를 부르면 실측 가능한 모양."""

    def get_cookies(self):
        raise RuntimeError("session deleted because of page crash (가짜)")


class _RaisingGetDriver:
    """driver.get() 자체가 죽는 대역 — threads.net SPA 상대로
    TimeoutException 이 나는 상황을 흉내낸다."""

    def get(self, url):
        raise TimeoutError("threads.net 응답 없음(가짜)")


# ── Finding 4: save_cookies() 는 OSError 뿐 아니라 드라이버 예외도
#    삼켜야 한다(참조 구현과 동일한 폭) ──────────────────────────
def test_save_cookies_survives_driver_exception(tmp_path, monkeypatch):
    auto = ThreadsAutomator(account="test_acct")
    monkeypatch.setattr(auto, "_cookie_path", lambda: tmp_path / "threads_test_acct.json")
    auto.driver = _RaisingCookieDriver()
    auto.save_cookies()  # 여기서 예외가 새어나가면 이 테스트 자체가 실패한다
    assert not (tmp_path / "threads_test_acct.json").exists()


# ── Finding 1: load_session() 은 driver.get() 예외를 삼키고 False 를
#    돌려줘야 한다(예외가 harvest() 로 새어나가면 안 되므로) ──────
def test_load_session_returns_false_when_driver_get_raises(tmp_path, monkeypatch):
    auto = ThreadsAutomator(account="test_acct2")
    cookie_file = tmp_path / "threads_test_acct2.json"
    cookie_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(auto, "_cookie_path", lambda: cookie_file)
    # driver 를 미리 꽂아 두면 start() 는 (self.driver is not None) 분기로
    # 즉시 반환한다 — selenium 을 import 하지 않고도 load_session() 의
    # 그 다음 단계(쿠키 적용)를 직접 겨눌 수 있다.
    auto.driver = _RaisingGetDriver()
    assert auto.load_session() is False


def test_load_session_returns_false_when_cookie_file_missing(tmp_path, monkeypatch):
    """기존 동작(쿠키 파일 자체가 없음)은 이번 수정으로 안 바뀌었는지
    회귀 확인 — 드라이버 예외 가드를 추가하며 이 얕은 경로를 건드리지
    않았음을 확인한다."""
    auto = ThreadsAutomator(account="test_acct3")
    monkeypatch.setattr(auto, "_cookie_path", lambda: tmp_path / "no_such_file.json")
    auto.driver = _RaisingGetDriver()  # 쿠키 파일이 없으니 여기까지 안 감
    assert auto.load_session() is False
