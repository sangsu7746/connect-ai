# ============================================================
#  channels/facebook.py — 페이스북 그룹 어댑터  (P1-3 확장)
#  래핑: 페이스북-광고글/app/facebook_automator.py (Selenium 스텔스·인간형 타이핑)
#    login(password) / post_to_group(group_url, text, image_paths) / get_group_list
#  ⚠ band.py 와 동일 3중 안전장치 (실발행 시에만 selenium 지연 import)
# ============================================================
import sys

import config
from channels.base import BaseAdapter, PostResult, Feedback


class FacebookAdapter(BaseAdapter):
    platform = "facebook"

    def __init__(self, account_id: str = "facebook_default", headless: bool = False):
        self.account_id = account_id
        self.headless = headless
        self._auto = None
        self._logged_in = False

    def _automator(self):
        if self._auto is None:
            # 페북은 '페이스북-회원자동포스팅' 프로그램의 엔진을 쓴다(성숙한 쪽).
            from . import engine
            mod = engine.load(config.FB_PROJECT_APP_DIR, "facebook_automator")
            self._auto = mod.FacebookAutomator(self.account_id, headless=self.headless)
        return self._auto

    @staticmethod
    def _valid_target(target: str) -> bool:
        return bool(target) and "facebook.com" in target and "/groups/" in target

    def login(self, cred: dict = None) -> bool:
        """cred 없이 호출하면 **저장된 세션(쿠키)만으로** 로그인 — 권장.
        세션은 `python login.py facebook --account ...` 로 한 번만 만들어 두면 된다."""
        auto = self._automator()
        if not cred or not cred.get("password"):
            import time
            if auto.driver is None:
                auto.driver = auto._create_driver()
            auto._load_cookies()
            auto.driver.get("https://www.facebook.com")
            time.sleep(3)
            self._logged_in = auto._is_logged_in()
            print(f"[fb:login] 저장된 세션 "
                  f"{'복원 성공' if self._logged_in else '만료 — login.py 로 재로그인 필요'}")
            return self._logged_in
        self._logged_in = auto.login(
            cred["password"], status_callback=lambda m: print(f"[fb:login] {m}"))
        return self._logged_in

    def post(self, target: str, text: str, image_path=None, dry_run: bool = True) -> PostResult:
        if not self._valid_target(target):
            return PostResult(ok=False, blocked=True, error=f"유효한 페북 그룹 URL 아님: {target!r}")

        if dry_run:
            self._log_dry("POST", target, text, image_path)
            return PostResult(ok=True, dry_run=True)

        if config.GLOBAL_DRY_RUN:
            return PostResult(ok=False, blocked=True,
                error="GLOBAL_DRY_RUN=1 — 실발행 차단(안전). 켜려면 .env에서 0으로.")
        if not self._rate_ok():
            return PostResult(ok=False, blocked=True,
                error=f"일일 발행 상한({config.DAILY_POST_LIMIT}건) 도달 — 계정 보호")
        if not self._logged_in:
            return PostResult(ok=False, blocked=True, error="로그인 필요 — login(cred) 먼저 호출")

        images = [image_path] if image_path else None
        auto = self._automator()
        ok = auto.post_to_group(
            target, text, image_paths=images,
            status_callback=lambda m: print(f"[fb:post] {m}"))
        # ⚠ 예전엔 그룹 주소를 perm_url 로 저장했다. 그러면 '그 글'로 되돌아갈 수 없어
        #   댓글·반응 측정이 불가능하다. 게시물 고유 주소를 우선 쓴다.
        perm = getattr(auto, "last_post_url", "") or ""
        return PostResult(ok=ok, perm_url=(perm or target) if ok else None,
                          error=None if ok else "게시 실패(셀렉터 변경/차단 가능)")

    def read_feedback(self, target: str, since=None) -> list:
        return []   # TODO(P2): 그룹 게시물 댓글 수집

    def send_reply(self, target: str, text: str, files=None, dry_run: bool = True) -> bool:
        if dry_run:
            self._log_dry("REPLY", target, text)
            return True
        return False   # TODO(P2): 페북 그룹 댓글 답글

    def discover_groups(self) -> list:
        if not self._logged_in:
            raise RuntimeError("로그인 필요")
        return self._automator().get_group_list(
            status_callback=lambda m: print(f"[fb:list] {m}"))

    def quit(self):
        if self._auto is not None:
            self._auto.quit()
            self._auto = None
