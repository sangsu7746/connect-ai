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

import random
import time

import config
import db
from channels.base import BaseAdapter, PostResult
from threads.reply_writer import _cp949_safe

# ── 셀렉터 (리뷰 라운드 1에서 상수로 분리 — 테스트가 문자열을 중복
#    하드코딩하지 않고 이 값을 직접 참조하게 하려는 목적) ──────────
_BOX_SELECTOR = "div[contenteditable='true'], textarea"
_PERM_SELECTOR = "a[href*='/post/']"
_MORE_SELECTOR = "svg[aria-label*='더'], [aria-label*='More']"
_DELETE_XPATH = "//*[text()='삭제' or text()='Delete']"

# ── 캡차/차단 감지 (리뷰 Finding 1) ─────────────────────────────
# 1순위 신호: URL 자체가 챌린지/체크포인트 경로로 리다이렉트됐는가.
# 메타 계열 공통 패턴으로 추정한 값이며, 이 프로젝트가 실제 차단 화면을
# 한 번도 실측하지 못한 상태라 근거가 약하다 — 첫 실발행 세션에서
# 사람이 직접 확인해 갱신할 것.
_CHALLENGE_URL_MARKERS = ("/challenge/", "/checkpoint/", "/accounts/suspended")
# 2순위 신호: 화면에 실제로 보이는 텍스트(요소.text)에서만 찾는다.
# page_source 전체(번들 스크립트 포함)를 보면 정상 페이지의 봇탐지
# 스크립트 참조나, 글쓴이가 우연히 쓴 "captcha" 라는 단어에도 걸려
# 기능 전체가 조용히 멈추는 사고가 난다(리뷰 Finding 1 재현). 그래서
# 반드시 '입력창이 없다'는 구조적 신호와 같이 나올 때만 판단 근거로
# 쓴다 — 진짜 차단 화면엔 답글창이 없다는 전제.
_CHALLENGE_PHRASES = ("captcha", "unusual activity", "일시적으로 차단")

# ── 타이핑 간격 (리뷰 Finding 4) ────────────────────────────────
# 완전히 균일한 간격 자체가 탐지 신호라 무작위 범위를 준다. 280자(설정
# 상한) 기준으로도 전체 흐름이 수 초~수십 초 안에 끝나도록 범위를
# 좁게 잡는다(분 단위로 늘어지면 그 자체가 다른 방식의 이상 신호다).
_TYPE_DELAY_MIN = 0.015
_TYPE_DELAY_MAX = 0.06


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
    def _rate_status(self, auto: bool = False) -> tuple:
        """판정(True/False)과 사유를 한 번의 조회로 함께 낸다.

        리뷰 Finding 3: _rate_ok() 와 _rate_reason() 을 따로 두 번
        부르면 db.threads_replies_today() 를 매번 새로 왕복하는데,
        그 사이 카운트가 바뀌면(동시에 다른 발행이 끼는 등) _rate_
        reason() 이 이미 지나간 상한 값을 못 찾아 빈 문자열을 내는
        경우가 생긴다 — blocked=True 인데 error="" 인, 운영자가
        이유를 알 수 없는 결과. 판정 시점의 카운트를 한 번만 읽어
        재사용해 이 레이스를 구조적으로 없앤다. reply() 는 이 메서드를
        직접 불러 왕복도 한 번으로 줄인다."""
        n = db.threads_replies_today()
        if n >= config.THREADS_DAILY_LIMIT:
            return False, f"오늘 답글 총 상한 도달({n}/{config.THREADS_DAILY_LIMIT}건) · 계정 보호"
        if auto:
            m = db.threads_replies_today(auto_only=True)
            if m >= config.THREADS_AUTO_DAILY_LIMIT:
                return False, (f"자동 발행 상한 도달({m}/{config.THREADS_AUTO_DAILY_LIMIT}건) · "
                                "무검수 발행량 제한. 승인 큐로는 계속 나갈 수 있습니다")
        return True, ""

    def _rate_ok(self, channel_id=None, auto: bool = False) -> bool:
        return self._rate_status(auto=auto)[0]

    def _rate_reason(self, channel_id=None, auto: bool = False) -> str:
        """막힌 이유를 사람 말로. 대시보드에 그대로 뜰 수 있으므로
        cp949 로 못 찍는 문자(em dash 등)는 쓰지 않는다."""
        return self._rate_status(auto=auto)[1]

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
    def _valid_target(url) -> bool:
        # 리뷰 Finding 2: url 이 str 이 아닐 수 있다(int/float/None 등이
        # 호출부 실수로 들어올 수 있음 — Task 6 은 이 값이 여러 층을
        # 거쳐 들어온다). isinstance 를 가장 먼저 봐서 "threads.net" in
        # url 같은 in-연산이 TypeError 를 던지기 전에 걸러낸다.
        return isinstance(url, str) and bool(url) and \
            "threads.net" in url and "/post/" in url

    # ── 발행 ────────────────────────────────────────────────────
    def reply(self, post_url: str, text: str, dry_run: bool = True,
              auto: bool = False) -> PostResult:
        """reply() 는 절대 예외를 밖으로 흘리지 않는다.

        리뷰 Finding 2: 예전엔 형식 검증(_valid_target 등)이 try 밖에
        있어서 post_url 이 str 이 아니면(int/float 등) 그 자리에서
        TypeError 가 그대로 새어나갔다 — "reply() 는 절대 raise 하지
        않는다"는 이 모듈이 채점받는 바로 그 속성이 깨지는 지점이었다.
        지금은 함수 몸통 전체(형식 검증~발행)를 하나의 try 로 감싸,
        `_valid_target()` 자체를 type-safe 하게 고친 것과 별개로 앞으로
        비슷한 실수가 또 나도 구조적으로 막히게 했다."""
        try:
            # 형식 검증은 dry-run 여부와 무관하게 항상 먼저 본다.
            if not self._valid_target(post_url):
                # post_url 이 이 시점에 뭐가 들어왔는지 모른다(str 아닌
                # 값도 포함) — repr() 은 비-ASCII 를 이스케이프하지
                # 않으므로 문자열화 + cp949 필터를 거쳐 그대로 찍는다.
                safe_url = _cp949_safe(str(post_url))
                return PostResult(ok=False, blocked=True,
                                  error=f"유효한 쓰레드 글 주소 아님: {safe_url!r}")
            if not (text or "").strip():
                return PostResult(ok=False, blocked=True, error="빈 답글")

            if dry_run:
                # text 는 LLM(reply_writer)이 만든 값이라 로그로 나가기
                # 전에 cp949-불가 문자를 거른다. post_url 은 _valid_
                # target() 이 부분 문자열만 확인하므로(전체 ASCII 를
                # 보장하지 않는다) target 쪽도 같이 거른다 — _log_dry()
                # 는 target 을 repr() 로 그대로 찍는데 repr() 은
                # 비-ASCII 를 이스케이프하지 않는다(reply_writer.
                # _cp949_safe 의 docstring과 같은 이유).
                self._log_dry("REPLY", _cp949_safe(post_url), _cp949_safe(text))
                return PostResult(ok=True, dry_run=True)

            # 여기서부터는 실제로 브라우저를 건드릴 수 있는 경로다. 이
            # 블록 안의 명시적 return 은 '의도된 차단'(blocked=True)이라
            # 예외로 새지 않고 정상적으로 빠져나간다 — 바깥 except 는
            # 오직 예상 못 한 실패만 잡는다.
            if not config.THREADS_ENABLED:
                return PostResult(ok=False, blocked=True,
                    error="THREADS_ENABLED=0 · 실발행 차단(안전). 켜려면 .env 에서 1로.")
            if config.GLOBAL_DRY_RUN:
                return PostResult(ok=False, blocked=True,
                    error="GLOBAL_DRY_RUN=1 · 실발행 차단(안전). 켜려면 .env 에서 0으로.")
            rate_ok, rate_reason = self._rate_status(auto=auto)
            if not rate_ok:
                return PostResult(ok=False, blocked=True, error=rate_reason)
            if not self._logged_in:
                return PostResult(ok=False, blocked=True,
                                  error="로그인 필요 · login() 먼저 호출")
            return self._do_reply(post_url, text)
        except Exception as e:
            # 셀렉터 변경·네트워크·타입 오류 등 진짜 실패. blocked 가
            # 아니라 error — 안전장치가 막은 게 아니라 뭔가 고장 났다는
            # 신호이므로 운영자가 헛짚지 않도록 구분한다(channels/
            # base.py 의 규약).
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

        # 1순위 신호: URL 이 챌린지/체크포인트 경로로 리다이렉트됐는가.
        # 페이지 내용을 전혀 안 봐도 되는 가장 싸고 확실한 신호라 먼저
        # 본다 — 여기서 걸리면 입력창 존재 여부와 무관하게 즉시 멈춘다.
        current_url = (getattr(d, "current_url", "") or "").lower()
        if any(marker in current_url for marker in _CHALLENGE_URL_MARKERS):
            return PostResult(ok=False, blocked=True,
                error="URL 이 캡차/체크포인트 경로로 리다이렉트됨 · 재시도 금지. "
                      "THREADS_ENABLED 를 0으로 내려 마스터 스위치를 꺼 두세요")

        boxes = d.find_elements(By.CSS_SELECTOR, _BOX_SELECTOR)

        if not boxes:
            # 입력창이 없다 — 셀렉터가 바뀐 것일 수도, 진짜 차단 화면
            # 일 수도 있다. 리뷰 Finding 1: page_source 전체(번들
            # 스크립트 포함)를 문구 매칭하면 정상 페이지의 봇탐지
            # 스크립트나 글쓴이가 우연히 쓴 단어에도 걸려 전체 기능이
            # 조용히 멈춘다 — 그래서 화면에 실제로 보이는 텍스트만
            # 보고, 그마저도 '입력창 부재'와 같이 나올 때만 판단한다
            # (진짜 차단 화면엔 답글창이 없다는 전제).
            body_text = ""
            try:
                body_text = (d.find_element(By.TAG_NAME, "body").text or "").lower()
            except Exception:
                pass
            if any(p in body_text for p in _CHALLENGE_PHRASES):
                return PostResult(ok=False, blocked=True,
                    error="캡차/차단 화면 감지(문구+입력창 부재) · 재시도 금지. "
                          "THREADS_ENABLED 를 0으로 내려 마스터 스위치를 꺼 두세요")
            # 안전장치가 막은 게 아니라 진짜 실패다.
            return PostResult(ok=False, error="답글 입력창 없음(셀렉터 변경 가능)")

        box = boxes[0]
        box.click()
        time.sleep(0.5)
        # 인간형 타이핑 — 한 번에 붙여넣으면 그 자체가 탐지 신호이고,
        # 간격이 완전히 균일해도 마찬가지다(리뷰 Finding 4) — 매 글자
        # 마다 무작위 간격을 준다.
        for ch in text:
            box.send_keys(ch)
            time.sleep(random.uniform(_TYPE_DELAY_MIN, _TYPE_DELAY_MAX))
        time.sleep(1)
        box.send_keys(Keys.CONTROL, Keys.ENTER)
        time.sleep(4)

        # 발행됐는지 확인. 주소를 못 찾아도 발행 자체는 성공일 수 있다 —
        # 이 경우 ok=True 를 유지하고 error 에는 사유만 남긴다(실패로
        # 보고하면 이미 나간 답글에 대해 운영자가 또 발행을 시도하게 된다).
        perm = ""
        try:
            for a in d.find_elements(By.CSS_SELECTOR, _PERM_SELECTOR):
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
        판단한다.

        리뷰 Finding 2: 형식 검증(_valid_target)이 예전엔 이 메서드의
        try 밖에 있었다 — reply() 와 같은 문제(str 아닌 값이면 raise)
        가 여기도 있었으므로 몸통 전체를 try 로 감싼다. 이 메서드의
        계약은 `-> bool` 이라 예외 대신 False 를 돌려주면 된다."""
        try:
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
            for btn in d.find_elements(By.CSS_SELECTOR, _MORE_SELECTOR):
                btn.click()
                time.sleep(1)
                for item in d.find_elements(By.XPATH, _DELETE_XPATH):
                    item.click()
                    time.sleep(1)
                    for ok in d.find_elements(By.XPATH, _DELETE_XPATH):
                        ok.click()
                        time.sleep(2)
                        return True
            return False
        except Exception:
            return False

    def quit(self):
        if self._auto is not None:
            self._auto.quit()
            self._auto = None
