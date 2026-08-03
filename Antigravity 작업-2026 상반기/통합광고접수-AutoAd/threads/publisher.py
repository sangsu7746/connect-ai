# ============================================================
#  threads/publisher.py — 답글 발행·삭제
#  · BaseAdapter 를 상속하되 상한 계산은 오버라이드한다.
#    기존 _rate_ok() 는 CHANNEL_DAILY_LIMIT(=1)을 보는데, 답글은 전부
#    채널 1행(@계정핸들)에 귀속되므로 그대로 쓰면 하루 첫 건 이후
#    전부 차단된다. 이건 dry-run 에선 안 드러나고 실발행 첫날에야 보인다.
#  · selenium 은 실발행 시에만 지연 import 한다(테스트가 브라우저 없이
#    돌아야 한다는 요구사항 때문).
#  · 콘솔/로그로 나가는 문자열 중 네트워크나 LLM 에서 온 값은 전부
#    threads.reply_writer._cp949_safe() 를 거친다 — cp949 콘솔에서
#    죽는 사고(threads 파이프라인에서 이미 한 번 겪음)를 여기서도
#    막기 위함이다. 예외 메시지도 마찬가지로 처리한다(harvester.py 의
#    기존 관례를 그대로 따른다).
# ============================================================
from __future__ import annotations

import time

import config
import db
from channels.base import BaseAdapter, PostResult
from threads.reply_writer import _cp949_safe


class ThreadsPublisher(BaseAdapter):
    platform = "threads"

    def __init__(self, account: str = "", headless: bool = None):
        self.account = account or config.THREADS_ACCOUNT
        self.headless = config.PUBLISH_HEADLESS if headless is None else headless
        self._auto = None
        self._logged_in = False

    # ── 상한 (오버라이드) ───────────────────────────────────────
    # BaseAdapter._rate_ok() 는 channel_id 별 CHANNEL_DAILY_LIMIT(=1)을
    # 보는데, 쓰레드 답글은 전부 채널 1행(계정 자신)에 귀속된다. 그대로
    # 쓰면 오늘 첫 답글 이후 전부 막힌다 — dry-run 으로는 절대 안
    # 드러나고 실발행 첫날에야 터진다. 그래서 THREADS_DAILY_LIMIT(총
    # 상한)과 THREADS_AUTO_DAILY_LIMIT(자동분 전용 상한)으로 완전히
    # 대체한다.
    def _rate_ok(self, channel_id=None, auto: bool = False) -> bool:
        if db.threads_replies_today() >= config.THREADS_DAILY_LIMIT:
            return False
        if auto and db.threads_replies_today(auto_only=True) >= \
                config.THREADS_AUTO_DAILY_LIMIT:
            return False
        return True

    def _rate_reason(self, channel_id=None, auto: bool = False) -> str:
        """막힌 이유를 사람 말로. 대시보드에 그대로 뜰 수 있으므로
        cp949 로 못 찍는 문자(em dash 등)는 쓰지 않는다."""
        n = db.threads_replies_today()
        if n >= config.THREADS_DAILY_LIMIT:
            return f"오늘 답글 총 상한 도달({n}/{config.THREADS_DAILY_LIMIT}건) · 계정 보호"
        if auto:
            m = db.threads_replies_today(auto_only=True)
            if m >= config.THREADS_AUTO_DAILY_LIMIT:
                return (f"자동 발행 상한 도달({m}/{config.THREADS_AUTO_DAILY_LIMIT}건) · "
                        "무검수 발행량 제한. 승인 큐로는 계속 나갈 수 있습니다")
        return ""

    # ── 세션 ────────────────────────────────────────────────────
    def _automator(self):
        if self._auto is None:
            from threads.automator import ThreadsAutomator
            self._auto = ThreadsAutomator(self.account, headless=self.headless)
        return self._auto

    def login(self, cred: dict = None) -> bool:
        """저장된 쿠키만으로 복원. 세션은 `python login.py threads` 로 만든다."""
        self._logged_in = self._automator().load_session()
        if not self._logged_in:
            print("[threads:login] 세션 만료 - python login.py threads 로 재로그인 필요")
        return self._logged_in

    @staticmethod
    def _valid_target(url: str) -> bool:
        return bool(url) and "threads.net" in url and "/post/" in url

    # ── 발행 ────────────────────────────────────────────────────
    def reply(self, post_url: str, text: str, dry_run: bool = True,
              auto: bool = False) -> PostResult:
        # 형식 검증은 dry-run 여부와 무관하게 항상 먼저 본다 — 브라우저를
        # 쓰지 않는 순수 문자열 검사라 안전장치를 하나 더 얹어도 비용이 없다.
        if not self._valid_target(post_url):
            # post_url 은 이 시점에 형식이 뭔지도 모르는 입력이다(None 도
            # 올 수 있다) — repr() 은 비-ASCII 를 이스케이프하지 않으므로
            # 그대로 찍기 전에 문자열화 + cp949 필터를 거친다.
            safe_url = _cp949_safe(str(post_url) if post_url is not None else "None")
            return PostResult(ok=False, blocked=True,
                              error=f"유효한 쓰레드 글 주소 아님: {safe_url!r}")
        if not (text or "").strip():
            return PostResult(ok=False, blocked=True, error="빈 답글")

        if dry_run:
            # text 는 LLM(reply_writer)이 만든 값이라 로그로 나가기 전에
            # cp949-불가 문자를 거른다. post_url 은 _valid_target() 이
            # 부분 문자열만 확인하므로(전체 ASCII 를 보장하지 않는다)
            # target 쪽도 같이 거른다 — _log_dry() 는 target 을 repr()
            # 로 그대로 찍는데 repr() 은 비-ASCII 를 이스케이프하지
            # 않는다(reply_writer._cp949_safe 의 docstring과 같은 이유).
            self._log_dry("REPLY", _cp949_safe(post_url), _cp949_safe(text))
            return PostResult(ok=True, dry_run=True)

        # 여기서부터는 실제로 브라우저를 건드릴 수 있는 경로다. reply() 는
        # 절대 예외를 밖으로 흘리면 안 된다는 요구사항이 있어, 안전장치
        # 판정(브리프 코드는 _do_reply() 만 감쌌지만 db 조회 등 판정
        # 자체도 실패할 수 있으므로) 부터 발행까지 한 덩어리로 감싼다.
        # 이 블록 안의 명시적 return 은 '의도된 차단'(blocked=True)이라
        # 예외로 새지 않고 정상적으로 빠져나간다 — except 는 오직
        # 예상 못 한 실패만 잡는다.
        try:
            if not config.THREADS_ENABLED:
                return PostResult(ok=False, blocked=True,
                    error="THREADS_ENABLED=0 · 실발행 차단(안전). 켜려면 .env 에서 1로.")
            if config.GLOBAL_DRY_RUN:
                return PostResult(ok=False, blocked=True,
                    error="GLOBAL_DRY_RUN=1 · 실발행 차단(안전). 켜려면 .env 에서 0으로.")
            if not self._rate_ok(auto=auto):
                return PostResult(ok=False, blocked=True, error=self._rate_reason(auto=auto))
            if not self._logged_in:
                return PostResult(ok=False, blocked=True,
                                  error="로그인 필요 · login() 먼저 호출")
            return self._do_reply(post_url, text)
        except Exception as e:
            # 셀렉터 변경·네트워크 등 진짜 실패. blocked 가 아니라 error —
            # 안전장치가 막은 게 아니라 뭔가 고장 났다는 신호이므로
            # 운영자가 헛짚지 않도록 구분한다(channels/base.py 의 규약).
            msg = _cp949_safe(str(e))[:200]
            return PostResult(ok=False, error=f"발행 실패({type(e).__name__}): {msg}",
                              blocked=False)

    def _do_reply(self, post_url: str, text: str) -> PostResult:
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys

        auto = self._automator()
        d = auto.driver
        d.get(post_url)
        time.sleep(3)

        # 캡차·차단 화면이면 즉시 멈춘다. 계속 두들기면 계정 정지로 가는
        # 지름길이다 — 재시도하지 않고 그 자리에서 blocked 로 반환한다.
        page = (d.page_source or "").lower()
        if "captcha" in page or "unusual activity" in page or "일시적으로 차단" in page:
            return PostResult(ok=False, blocked=True,
                error="캡차/차단 화면 감지 · 재시도 금지. THREADS_ENABLED 를 0으로 "
                      "내려 마스터 스위치를 꺼 두세요")

        boxes = d.find_elements(By.CSS_SELECTOR,
                                "div[contenteditable='true'], textarea")
        if not boxes:
            # 셀렉터가 바뀐 것 — 안전장치가 막은 게 아니라 진짜 실패다.
            return PostResult(ok=False, error="답글 입력창 없음(셀렉터 변경 가능)")

        box = boxes[0]
        box.click()
        time.sleep(0.5)
        # 인간형 타이핑 — 한 번에 붙여넣으면 그 자체가 탐지 신호가 된다.
        for ch in text:
            box.send_keys(ch)
            time.sleep(0.02)
        time.sleep(1)
        box.send_keys(Keys.CONTROL, Keys.ENTER)
        time.sleep(4)

        # 발행됐는지 확인. 주소를 못 찾아도 발행 자체는 성공일 수 있다 —
        # 이 경우 ok=True 를 유지하고 error 에는 사유만 남긴다(실패로
        # 보고하면 이미 나간 답글에 대해 운영자가 또 발행을 시도하게 된다).
        perm = ""
        try:
            for a in d.find_elements(By.CSS_SELECTOR, "a[href*='/post/']"):
                href = a.get_attribute("href") or ""
                if self.account and f"@{self.account}" in href:
                    perm = href
                    break
        except Exception:
            pass
        return PostResult(ok=True, perm_url=perm or None,
                          error=None if perm else "발행됨(주소 확인 실패)")

    def delete_reply(self, reply_url: str, dry_run: bool = True) -> bool:
        """잘못 나간 답글 회수. 자동 발행을 켜는 이상 반드시 있어야 하는 손잡이.

        THREADS_ENABLED·GLOBAL_DRY_RUN 은 일부러 보지 않는다 — 이 둘은
        '실발행'을 막는 마스터 스위치인데, 회수(삭제)까지 막으면 마스터
        스위치를 끈 바로 그 순간에 잘못 나간 글을 치울 방법이 없어진다.
        실행 여부는 오직 이 메서드 자신의 dry_run 인자와 로그인 상태로만
        판단한다."""
        if not self._valid_target(reply_url):
            return False
        if dry_run:
            self._log_dry("DELETE", _cp949_safe(reply_url))
            return True
        if not self._logged_in:
            return False
        from selenium.webdriver.common.by import By
        d = self._automator().driver
        d.get(reply_url)
        time.sleep(3)
        try:
            for btn in d.find_elements(By.CSS_SELECTOR, "svg[aria-label*='더'], [aria-label*='More']"):
                btn.click()
                time.sleep(1)
                for item in d.find_elements(By.XPATH, "//*[text()='삭제' or text()='Delete']"):
                    item.click()
                    time.sleep(1)
                    for ok in d.find_elements(By.XPATH, "//*[text()='삭제' or text()='Delete']"):
                        ok.click()
                        time.sleep(2)
                        return True
        except Exception:
            return False
        return False

    def quit(self):
        if self._auto is not None:
            self._auto.quit()
            self._auto = None
