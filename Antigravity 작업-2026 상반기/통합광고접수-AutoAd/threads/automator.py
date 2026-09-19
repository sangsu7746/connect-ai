# ============================================================
#  threads/automator.py — Selenium 드라이버·쿠키·스텔스
#  이식: 페이스북-회원자동포스팅/app/facebook_automator.py:130-181
#  · 스레드도 Meta라 같은 탐지 계열을 받는다. 실전에서 살아남은
#    설정을 그대로 쓴다(navigator.webdriver 은폐·excludeSwitches).
#  · selenium 은 지연 import — 테스트가 브라우저 없이 돌아야 한다.
# ============================================================
from __future__ import annotations

import json
import time
from pathlib import Path

import config

THREADS_HOME = "https://www.threads.net"


def cookie_dir() -> Path:
    """페북 자동포스팅 프로그램의 쿠키 폴더를 함께 쓴다.
    (같은 PC·같은 사람이 관리하므로 흩어놓을 이유가 없다)"""
    root = Path(config.FB_PROJECT_APP_DIR).parent
    d = root / "data" / "cookies"
    d.mkdir(parents=True, exist_ok=True)
    return d


class ThreadsAutomator:
    def __init__(self, account: str = "", headless: bool = True):
        self.account = account or config.THREADS_ACCOUNT
        self.headless = headless
        self.driver = None

    def _cookie_path(self) -> Path:
        return cookie_dir() / f"threads_{self.account}.json"

    def start(self):
        if self.driver is not None:
            return self.driver
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        from selenium.webdriver.chrome.service import Service
        from webdriver_manager.chrome import ChromeDriverManager

        opts = Options()
        if self.headless:
            opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1280,900")
        opts.add_argument("--lang=ko-KR")
        opts.add_argument("--disable-notifications")
        opts.add_experimental_option("excludeSwitches", ["enable-automation"])
        opts.add_experimental_option("useAutomationExtension", False)
        try:
            self.driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()), options=opts)
        except Exception:
            self.driver = webdriver.Chrome(options=opts)
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
        self.driver.set_page_load_timeout(30)
        return self.driver

    def save_cookies(self):
        """⚠ 리뷰 Finding 4: OSError 만 잡으면 죽은 드라이버 세션에서
        get_cookies() 가 던지는 WebDriverException(사람이 2FA·캡차를
        오래 붙잡고 있다 세션이 끊기는 경우 실측 가능)이 그대로 새어나가
        login_threads() 를 깨뜨린다. 참조 구현(facebook_automator.
        _save_cookies)도 전체를 Exception 으로 감싼다 — 그대로 맞춘다."""
        if not self.driver:
            return
        try:
            self._cookie_path().write_text(
                json.dumps(self.driver.get_cookies(), ensure_ascii=False),
                encoding="utf-8")
        except Exception:
            pass

    def load_session(self) -> bool:
        """저장된 쿠키로 세션 복원. 성공하면 True.

        ⚠ 리뷰 Finding 1: driver.get() 두 곳이 무방비였다 — threads.net
        SPA 상대로 TimeoutException 은 충분히 있을 수 있는 일이고, 이게
        여기서 새어나가면 harvest() 의 try/finally(except 없음)를 그대로
        뚫고 나가 '수집 0건' 대신 진짜 크래시가 된다. 쿠키 적용까지
        한 덩어리로 감싼다(참조 구현 facebook_automator._load_cookies
        와 같은 폭)."""
        self.start()
        p = self._cookie_path()
        if not p.exists():
            return False
        try:
            cookies = json.loads(p.read_text(encoding="utf-8"))
            self.driver.get(THREADS_HOME)
            time.sleep(2)
            for c in cookies:
                try:
                    self.driver.add_cookie(c)
                except Exception:
                    continue
            self.driver.get(THREADS_HOME)
            time.sleep(3)
            return self.is_logged_in()
        except Exception:
            # OSError/ValueError(쿠키 파일 손상)와 TimeoutException 등
            # 드라이버 예외를 한 번에 받는다 — 어느 쪽이든 '세션 복원
            # 실패'로 동일하게 처리하면 되므로 구분할 이유가 없다.
            return False

    # 스레드는 인스타그램 세션 위에 올라간다. 이 쿠키들이 곧 로그인 증거다.
    _AUTH_COOKIES = ("sessionid", "ds_user_id")

    def is_logged_in(self) -> bool:
        """세션 쿠키가 있으면 로그인 상태로 본다.

        ⚠ 예전에는 DOM 을 추측했다 — '[href=/login] 이 없고 svg[aria-label]
          이 있으면 로그인'. 그런데 로그인 **페이지 자체**에는 /login 링크가
          없고(이미 거기 있으므로) 아이콘 SVG 는 있다. 그래서 로그인 창을
          띄운 직후 곧바로 True 가 났고, 로그인 전 쿠키(csrftoken·ig_did)
          2개만 저장된 채 '성공'으로 보고됐다(실측 2026-08-04).

          쿠키는 추측이 아니다. 브라우저가 서버에서 받은 사실이고, Meta 가
          DOM 을 바꿔도 인증 방식이 바뀌지 않는 한 그대로다."""
        if not self.driver:
            return False
        try:
            names = {c.get("name") for c in self.driver.get_cookies()}
        except Exception:
            return False
        return any(n in names for n in self._AUTH_COOKIES)

    def quit(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
