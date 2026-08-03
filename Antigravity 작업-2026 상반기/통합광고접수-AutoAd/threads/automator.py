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
        if not self.driver:
            return
        try:
            self._cookie_path().write_text(
                json.dumps(self.driver.get_cookies(), ensure_ascii=False),
                encoding="utf-8")
        except OSError:
            pass

    def load_session(self) -> bool:
        """저장된 쿠키로 세션 복원. 성공하면 True."""
        self.start()
        p = self._cookie_path()
        if not p.exists():
            return False
        try:
            cookies = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
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

    def is_logged_in(self) -> bool:
        """작성창 진입점이 보이면 로그인 상태로 본다.
        (로그인 페이지의 '로그인' 버튼 유무보다 안정적이다)"""
        if not self.driver:
            return False
        try:
            from selenium.webdriver.common.by import By
            if self.driver.find_elements(By.CSS_SELECTOR, "[href='/login']"):
                return False
            return bool(self.driver.find_elements(
                By.CSS_SELECTOR, "[data-pressable-container], svg[aria-label]"))
        except Exception:
            return False

    def quit(self):
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
