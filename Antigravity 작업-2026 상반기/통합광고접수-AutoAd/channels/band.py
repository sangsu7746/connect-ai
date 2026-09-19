# ============================================================
#  channels/band.py — 네이버 밴드 어댑터  (P1-3)
#  래핑: 페이스북-광고글/app/band_automator.py (Selenium 스텔스)
#    login(password, login_type) / post_to_band(url, text, image_paths) / post_to_chat
#  ⚠ 실발행은 ToS·계정정지 리스크. 3중 안전장치:
#     ① 대상 URL 검증 ② GLOBAL_DRY_RUN 실발행 차단 ③ 일일 발행 상한
#  · BandAutomator 는 실발행 시에만 지연 import (dry-run은 selenium 불필요)
# ============================================================
import sys
from datetime import date

import config
import db
from channels.base import BaseAdapter, PostResult, Feedback


class BandAdapter(BaseAdapter):
    platform = "band"

    def __init__(self, account_id: str = "naver_default", headless: bool = False):
        self.account_id = account_id
        self.headless = headless
        self._auto = None
        self._logged_in = False

    # ── 지연 로딩(실발행 시에만 selenium 필요) ──────────────
    def _automator(self):
        if self._auto is None:
            # 밴드는 '네이버밴드-자동포스팅' 프로그램의 엔진을 쓴다(성숙한 쪽).
            from . import engine
            mod = engine.load(config.BAND_PROJECT_APP_DIR, "band_automator")
            self._auto = mod.BandAutomator(self.account_id, headless=self.headless)
        return self._auto

    # ── 안전장치 ────────────────────────────────────────────
    @staticmethod
    def _valid_target(target: str) -> bool:
        return bool(target) and "band.us" in target

    # _rate_ok 는 base.BaseAdapter 것을 쓴다.
    # (예전엔 여기 복사본이 있어 채널별 상한이 적용되지 않았다)

    # ── 어댑터 인터페이스 ───────────────────────────────────
    def login(self, cred: dict = None) -> bool:
        """cred 없이 호출하면 **저장된 세션(쿠키)만으로** 로그인한다 — 권장 방식.
        (세션은 `python login.py band --account ...` 로 한 번만 만들어 두면 된다.
         그래야 비밀번호가 코드·설정 어디에도 남지 않는다.)
        cred={'password':...} 를 주면 기존 엔진의 자격증명 로그인 경로를 쓴다."""
        auto = self._automator()
        if not cred or not cred.get("password"):
            self._logged_in = self._session_login(auto, "https://www.band.us/home")
            return self._logged_in
        self._logged_in = auto.login(
            cred["password"], cred.get("login_type", "naver"),
            status_callback=lambda m: print(f"[band:login] {m}"))
        return self._logged_in

    @staticmethod
    def _session_login(auto, home: str) -> bool:
        """저장된 쿠키로 세션 복원. 만료면 False (비밀번호를 요구하지 않는다)."""
        import time
        if auto.driver is None:
            auto.driver = auto._create_driver()
        auto._load_cookies()
        auto.driver.get(home)
        time.sleep(3)
        ok = auto._is_logged_in()
        print(f"[band:login] 저장된 세션 {'복원 성공' if ok else '만료 — login.py 로 재로그인 필요'}")
        return ok

    def post(self, target: str, text: str, image_path=None, dry_run: bool = True) -> PostResult:
        if not self._valid_target(target):
            return PostResult(ok=False, blocked=True, error=f"유효한 밴드 URL 아님: {target!r}")

        if dry_run:
            self._log_dry("POST", target, text, image_path)
            return PostResult(ok=True, dry_run=True)

        # ── 실발행 경로: 3중 안전장치 ──
        if config.GLOBAL_DRY_RUN:
            return PostResult(ok=False, blocked=True,
                error="GLOBAL_DRY_RUN=1 — 실발행 차단(안전). 켜려면 .env에서 0으로.")
        if not self._rate_ok():
            return PostResult(ok=False, blocked=True,
                error=f"일일 발행 상한({config.DAILY_POST_LIMIT}건) 도달 — 계정 보호")
        if not self._logged_in:
            return PostResult(ok=False, blocked=True, error="로그인 필요 — login(cred) 먼저 호출")

        auto = self._automator()
        images = [image_path] if image_path else None
        ok = auto.post_to_band(target, text, image_paths=images,
                               status_callback=lambda m: print(f"[band:post] {m}"))
        return PostResult(ok=ok, perm_url=(target if ok else None),
                          error=None if ok else "게시 실패(셀렉터 변경/캡차/차단 가능)")

    def read_feedback(self, target: str, since=None) -> list:
        # TODO(P2): 밴드 게시물 댓글 수집 → Feedback. 현재 발행엔진은 one-way.
        return []

    def send_reply(self, target: str, text: str, files=None, dry_run: bool = True) -> bool:
        """밴드 채팅방(chat_url) 메시지 전송."""
        if dry_run:
            self._log_dry("REPLY", target, text)
            return True
        if config.GLOBAL_DRY_RUN:
            print("[band] GLOBAL_DRY_RUN=1 — 실전송 차단")
            return False
        return self._automator().post_to_chat(
            target, text, status_callback=lambda m: print(f"[band:chat] {m}"))

    # ── 발행 대상 발견(선택) ────────────────────────────────
    def discover_bands(self) -> list:
        """로그인 후 내 밴드 목록 조회 → 채널 등록용."""
        if not self._logged_in:
            raise RuntimeError("로그인 필요")
        return self._automator().get_band_list(
            status_callback=lambda m: print(f"[band:list] {m}"))

    def quit(self):
        if self._auto is not None:
            self._auto.quit()
            self._auto = None
