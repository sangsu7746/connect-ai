# ============================================================
#  channels/threads.py — 쓰레드 답글 어댑터  (Task 7)
#  · ChannelAdapter 규격(post(target, text, image_path=None, dry_run=True))
#    뒤로 threads.publisher.ThreadsPublisher.reply() 를 감춘다.
#  · target 은 이 채널의 핸들이 아니라 답글을 달 **원글 URL** 이다 —
#    band/facebook/kakao 세 어댑터와 유일하게 다른 지점이고, 그 차이를
#    orchestrator.publish_creative() 가 알아야 한다(Task 7 디스패치
#    항목 3). 이 파일 자체는 그 사실을 몰라도 된다 — 받은 target 문자열을
#    그대로 ThreadsPublisher.reply(post_url=target, ...) 에 넘길 뿐이다.
#  · image_path 는 무시한다 — 답글은 텍스트 전용이다(디스패치 명시).
#  · _rate_ok/_rate_reason 을 오버라이드한다. BaseAdapter 것을 그대로
#    쓰면 channel_id 단위 CHANNEL_DAILY_LIMIT(기본 1)이 적용되는데,
#    쓰레드 답글은 전부 채널 1행(계정 자신)에 귀속되므로 오늘 첫 건
#    이후 전부 막힌다 — threads/publisher.py(Task 5)가 이미 풀어 놓은
#    계정 전체 상한(THREADS_DAILY_LIMIT) 로직을 그대로 위임한다.
#    승인 경로로 나가는 답글은 사람이 이미 검수했으므로 auto=False 로
#    고정한다(THREADS_AUTO_DAILY_LIMIT 은 무검수 자동발행 전용 상한이라
#    승인분을 거기 섞으면 안 된다).
#  · login()/_logged_in/_login_at/account_id/platform 은 orchestrator.
#    ensure_login() 이 어댑터 자신에게 직접 기대하는 속성/메서드다
#    (band/facebook 어댑터와 같은 계약) — ThreadsPublisher 를 감싸는
#    이 클래스가 그 값들을 그대로 노출한다.
#  · _auto 를 프로퍼티로 노출한다. orchestrator._close()/_session_
#    still_valid() 가 `adapter._auto.driver` 를 직접 들여다봐서 브라우저를
#    정리한다(band/facebook 과 동일한 관례) — 감싸기만 하고 밖으로
#    노출하지 않으면 쓰레드 실발행 이후 크롬 프로세스가 안 닫힌다.
# ============================================================
from __future__ import annotations

from typing import Optional

from channels.base import BaseAdapter, PostResult
from threads.publisher import ThreadsPublisher


class ThreadsAdapter(BaseAdapter):
    platform = "threads"

    def __init__(self, account_id: str = None, headless: bool = None):
        self.account_id = account_id or ""
        # account_id 가 비어 있으면 빈 문자열을 그대로 넘긴다 — ThreadsPublisher
        # 는 falsy account 를 config.THREADS_ACCOUNT 로 스스로 대체한다.
        self._pub = ThreadsPublisher(account=self.account_id, headless=headless)
        self._logged_in = False
        self._login_at = 0

    # orchestrator._close()/_session_still_valid() 가 이 이름을 직접 본다
    # (band/facebook 어댑터에서 self._auto 가 자동화 객체 그 자체인 것과
    #  같은 자리). 실제 자동화 객체는 ThreadsPublisher 가 지연 생성해
    # 들고 있으므로 그쪽을 그대로 비춘다.
    @property
    def _auto(self):
        return self._pub._auto

    # ── 세션 ────────────────────────────────────────────────────
    def login(self, cred: dict = None) -> bool:
        """저장된 쿠키만으로 복원한다. ThreadsPublisher.login() 은 cred 를
        보지 않는다(쓰레드는 비밀번호 재로그인 경로가 없다 — Task 5 설계).
        세션이 만료됐으면 `python login.py threads` 로 다시 만들어야
        한다는 안내는 orchestrator.ensure_login() 이 stored_credential()
        실패 경로에서 이미 내보낸다."""
        ok = self._pub.login()
        self._logged_in = ok
        return ok

    # ── 발행 ────────────────────────────────────────────────────
    def post(self, target: str, text: str, image_path: Optional[str] = None,
             dry_run: bool = True) -> PostResult:
        # image_path 는 답글에 쓰이지 않는다 — 의도적으로 무시.
        return self._pub.reply(target, text, dry_run=dry_run, auto=False)

    def read_feedback(self, target: str, since=None) -> list:
        return []   # TODO(P2): 답글에 달린 재답글 수집

    def send_reply(self, target: str, text: str, files=None, dry_run: bool = True) -> bool:
        # 이 채널에서 '답글'은 post() 그 자체다(원글에 대한 응답이 곧 발행).
        res = self.post(target, text, dry_run=dry_run)
        return bool(res.ok)

    # ── 상한 (오버라이드 — 모듈 docstring 참고) ────────────────────
    def _rate_ok(self, channel_id=None, auto: bool = False) -> bool:
        return self._pub._rate_ok(channel_id=channel_id, auto=auto)

    def _rate_reason(self, channel_id=None, auto: bool = False) -> str:
        return self._pub._rate_reason(channel_id=channel_id, auto=auto)

    def quit(self):
        self._pub.quit()
