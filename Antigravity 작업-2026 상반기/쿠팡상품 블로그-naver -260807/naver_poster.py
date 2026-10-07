"""
naver_poster.py
Selenium을 사용하여 네이버 블로그에 자동으로 글을 포스팅하는 모듈.
모든 동작은 사람이 직접 조작하는 것처럼 설계하여 봇 감지 시스템 우회를 최우선합니다.
"""
import os
import time
import random
import re
import json
import pyperclip
from contextlib import contextmanager
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


# ── 타이핑/행동 속도 프로파일 ──────────────────────────────────────────
_T_CHAR    = (0.04, 0.11)   # 일반 글자 딜레이
_T_PUNCT   = (0.13, 0.30)   # 쉼표·세미콜론 뒤 자연스러운 멈춤
_T_SENT    = (0.45, 1.20)   # 문장 끝(. ! ?) 뒤 멈춤
_T_PARA    = (0.70, 1.80)   # 단락 끝(\n) 뒤 멈춤
_T_THINK   = (1.50, 4.00)   # 가끔 멍 때리는 시간 (약 0.4% 확률)
_T_HOVER   = (0.15, 0.45)   # 마우스 hover → 클릭까지 시간
_T_PAGE    = (2.00, 3.50)   # 페이지 로드 후 안정화 시간

#: 전체 속도 배수. config.json 의 naver_speed 로 조절한다.
#:   1   기존(사람처럼 느리게)
#:   10  10배 빠름 — 글 1건 25분 → 5분 안팎
#:   50  거의 즉시. 본문은 클립보드로 한 번에 붙여넣는다
#: 올릴수록 네이버가 자동화로 볼 여지가 커진다. 계정을 잃으면 되돌릴 수 없으니
#: 한 번에 최대로 올리지 말고 며칠 지켜보며 단계적으로 올리는 편이 안전하다.
try:
    import json as _json
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
              encoding="utf-8") as _f:
        SPEED = float(_json.load(_f).get("naver_speed", 1.0) or 1.0)
except Exception:
    SPEED = 1.0
SPEED = max(1.0, min(SPEED, 100.0))

#: 아무리 빨라도 이만큼은 기다린다. 0 으로 두면 화면이 못 따라와 조용히 실패한다.
_MIN_WAIT = 0.02

#: 이 배수 이상이면 본문을 한 글자씩 치지 않고 클립보드로 붙여넣는다.
#: 붙여넣기는 사람도 늘 하는 동작이라, 비현실적으로 빠른 타건보다 오히려 자연스럽다.
_PASTE_THRESHOLD = 8.0

# CDP로 주입할 자동화 지문 은폐 스크립트 ─────────────────────────────
_STEALTH_JS = """
    // webdriver 속성 숨기기
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 플러그인 목록 조작 (빈 배열이면 headless로 의심됨)
    Object.defineProperty(navigator, 'plugins', {
        get: () => { const a = [1,2,3,4,5]; a.__proto__ = PluginArray.prototype; return a; }
    });

    // 언어 설정을 한국어로
    Object.defineProperty(navigator, 'languages', {
        get: () => ['ko-KR', 'ko', 'en-US', 'en']
    });

    // chrome 런타임 객체 (headless에서는 없어서 탐지됨)
    if (!window.chrome) { window.chrome = {}; }
    if (!window.chrome.runtime) { window.chrome.runtime = {}; }

    // Notification.permission 쿼리 위장
    const _origQuery = window.navigator.permissions.query.bind(navigator.permissions);
    window.navigator.permissions.query = (p) =>
        p.name === 'notifications'
            ? Promise.resolve({ state: Notification.permission })
            : _origQuery(p);

    // WebGL 렌더러 위장 (headless 탐지 우회)
    const _getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel(R) Iris(TM) Plus Graphics 640';
        return _getParam.call(this, p);
    };

    // console.debug 를 통한 자동화 탐지 차단
    const _origDebug = console.debug;
    console.debug = (...args) => {
        if (args[0] && String(args[0]).includes('cdc_')) return;
        _origDebug.apply(console, args);
    };
"""


class NaverBlogPoster:
    """네이버 블로그 자동 포스팅 클래스 (봇 감지 최소화 설계)"""

    NAVER_LOGIN_URL      = "https://nid.naver.com/nidlogin.login"
    NAVER_BLOG_WRITE_URL = "https://blog.naver.com/PostWriteForm.naver"

    def __init__(self, headless: bool = False, log_callback=None):
        self.driver   = None
        self.headless = headless
        self.log      = log_callback or print

    # ── 드라이버 초기화 ───────────────────────────────────────────────
    def _init_driver(self) -> None:
        options = Options()
        if self.headless:
            options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-infobars")
        options.add_argument("--lang=ko-KR")
        options.add_experimental_option("excludeSwitches", ["enable-automation", "enable-logging"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_argument(
            "user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
        self.driver = webdriver.Chrome(options=options)

        # CDP로 모든 새 페이지마다 자동화 지문 은폐 스크립트 주입
        try:
            self.driver.execute_cdp_cmd(
                "Page.addScriptToEvaluateOnNewDocument",
                {"source": _STEALTH_JS}
            )
        except Exception:
            # CDP 미지원 환경에서는 일회성 JS 실행으로 대체
            self.driver.execute_script(_STEALTH_JS)

        self.driver.implicitly_wait(10)

    # ── 쿠키 관리 ────────────────────────────────────────────────────
    def _cookie_path(self) -> str:
        import os
        return os.path.join(os.path.expanduser("~"), ".naver_poster_cookies.pkl")

    def _save_cookies(self) -> None:
        import pickle
        try:
            with open(self._cookie_path(), "wb") as f:
                pickle.dump(self.driver.get_cookies(), f)
        except Exception:
            pass

    def _load_cookies_and_check(self) -> bool:
        import pickle, os
        path = self._cookie_path()
        if not os.path.exists(path):
            return False
        try:
            self.driver.get("https://www.naver.com/")
            self._rnd_wait(*_T_PAGE)
            with open(path, "rb") as f:
                cookies = pickle.load(f)
            for cookie in cookies:
                try:
                    self.driver.add_cookie(cookie)
                except Exception:
                    pass
            self.driver.refresh()
            self._rnd_wait(*_T_PAGE)

            # 판정은 마크업이 아니라 '동작'으로 한다.
            # 예전에는 href 에 logout 이 든 <a> 를 찾았는데, 네이버 메인이 바뀌면
            # 세션이 멀쩡해도 복원 실패로 판정돼 매번 재로그인 + 2차 인증을 요구했다.
            # 로그인이 필요한 페이지를 열어 로그인 화면으로 튕기는지만 보면 된다.
            self.driver.get("https://blog.naver.com/MyBlog.naver")
            self._rnd_wait(*_T_PAGE)
            url = self.driver.current_url or ""
            if "nidlogin" not in url and "nid.naver.com" not in url:
                self.log("✅ 저장된 쿠키로 로그인 세션 복원 성공!")
                return True

            self.log("  ↺ 저장된 세션이 만료됐습니다 — 다시 로그인합니다.")
            return False
        except Exception:
            return False

    # ── 사람다운 동작 헬퍼 ──────────────────────────────────────────
    def _wait(self, seconds: float = 1.5) -> None:
        time.sleep(max(seconds / SPEED, _MIN_WAIT))

    def _rnd_wait(self, lo: float, hi: float) -> None:
        """
        모든 대기가 여기를 지난다. SPEED 로 한 번에 조절한다.

        하한(_MIN_WAIT)을 두는 이유: 대기를 0 으로 만들면 에디터가 준비되기 전에
        다음 동작이 들어가 조용히 실패한다(카테고리 선택·이미지 삽입이 특히 그렇다).
        빠르게 하되 화면이 따라올 시간은 남긴다.
        """
        time.sleep(max(random.uniform(lo, hi) / SPEED, _MIN_WAIT))

    @contextmanager
    def _no_implicit_wait(self):
        """
        '있으면 잡고 없으면 넘어간다'로 셀렉터를 훑는 구간에서 암묵 대기를 끈다.

        ■ 왜 필요한가 (2026-08-27 실측)

        생성자에 implicitly_wait(10) 이 걸려 있다. 이러면 find_elements 가 아무것도
        못 찾을 때 **10초를 꼬박 기다린 뒤** 빈 목록을 준다. 서식 툴바를 다루는
        코드는 후보 셀렉터를 예닐곱 개씩 늘어놓고 훑는데, 네이버 에디터가 바뀌어
        대부분이 빗나가므로 그 10초가 매번 쌓인다.

        로그에 정확히 찍혔다 — 단락 하나에 2분 01초, 19단락짜리 글 하나에 38분.
        10건이면 6시간이 넘는다. 실제로 그래서 하루치가 안 끝나고 있었다.

        naver_speed 를 100 으로 올려도 이건 안 줄어든다. 그 값은 _rnd_wait 만
        나누고, 암묵 대기는 셀레늄 내부에서 걸리기 때문이다. 그동안 속도를
        올려도 체감이 없던 이유가 이것이다.
        """
        self.driver.implicitly_wait(0)
        try:
            yield
        finally:
            # 로그인·에디터 로딩 쪽은 이 대기에 기대고 있으므로 반드시 되돌린다
            try:
                self.driver.implicitly_wait(10)
            except Exception:
                pass

    def _human_click(self, element) -> None:
        """마우스를 요소로 자연스럽게 이동 후 랜덤 딜레이를 두고 클릭."""
        try:
            ActionChains(self.driver).move_to_element(element).perform()
            self._rnd_wait(*_T_HOVER)
            element.click()
        except Exception:
            self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", element)
            self._wait(0.5)
            ActionChains(self.driver).move_to_element(element).click().perform()

    # 이모지·특수 유니코드 감지 패턴
    _EMOJI_RE = re.compile(
        r'[\U0001F000-\U0001FFFF'   # 이모지 메인 범위
        r'☀-➿'            # 기호·화살표·딩뱃
        r'⌀-⏿'            # 기타 기술 기호
        r'■-◿'            # 기하학 도형
        r'✀-➿'            # 딩뱃
        r'︀-️'            # 변형 선택자
        r'‍'                   # ZWJ (이모지 결합)
        r']'
    )

    def _clipboard_paste(self, text: str) -> None:
        """텍스트를 클립보드에 복사한 뒤 Ctrl+V로 붙여넣기."""
        pyperclip.copy(text)
        ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('v').key_up(Keys.CONTROL).perform()
        self._rnd_wait(0.05, 0.12)

    def _human_type(self, text: str,
                    min_d: float = _T_CHAR[0],
                    max_d: float = _T_CHAR[1]) -> None:
        """
        사람처럼 타이핑.
        - 이모지·특수 유니코드: send_keys가 전송 불가 → 클립보드 붙여넣기
        - 일반 문자: 한 글자씩 딜레이 타이핑
        - 구두점·문장 끝·단락에서 자연스러운 멈춤 삽입
        """
        # ── 빠른 모드: 클립보드로 통째 붙여넣기 ──────────────────────
        # 한 글자씩 치면 700자에 약 90초가 든다. 붙여넣기는 한순간이고,
        # 사람도 늘 하는 동작이라 비현실적으로 빠른 타건보다 자연스럽다.
        # 줄바꿈은 붙여넣기로 들어가지 않는 경우가 있어 줄 단위로 나눠 처리한다.
        if SPEED >= _PASTE_THRESHOLD and len(text) > 12:
            for k, line in enumerate(text.split("\n")):
                if k:
                    ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                    self._rnd_wait(*_T_PARA)
                if line:
                    self._clipboard_paste(line)
            return

        i = 0
        char_count = 0
        while i < len(text):
            char = text[i]

            # ── 이모지 / 특수 유니코드 → 클립보드 방식 ──────────────────
            if self._EMOJI_RE.match(char) or ord(char) > 0xFFFF:
                # 연속된 이모지/특수문자를 한 덩어리로 모아 한 번에 붙여넣기
                chunk = char
                j = i + 1
                while j < len(text) and (
                    self._EMOJI_RE.match(text[j]) or ord(text[j]) > 0xFFFF
                    or text[j] == '‍'  # ZWJ
                ):
                    chunk += text[j]
                    j += 1
                self._clipboard_paste(chunk)
                i = j
                continue

            # ── 줄바꿈 ────────────────────────────────────────────────
            if char == "\n":
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._rnd_wait(*_T_PARA)
                i += 1
                continue

            # ── 문장 끝 부호 ──────────────────────────────────────────
            if char in ".!?。":
                ActionChains(self.driver).send_keys(char).perform()
                self._rnd_wait(*_T_SENT)
                i += 1
                char_count += 1
                continue

            # ── 구두점 ────────────────────────────────────────────────
            if char in ",;:、":
                ActionChains(self.driver).send_keys(char).perform()
                self._rnd_wait(*_T_PUNCT)
                i += 1
                char_count += 1
                continue

            # ── 일반 문자 ─────────────────────────────────────────────
            ActionChains(self.driver).send_keys(char).perform()
            self._rnd_wait(min_d, max_d)
            i += 1
            char_count += 1

            # 약 0.4% 확률로 긴 멈춤 (사람이 잠시 멍 때리는 효과)
            if char_count > 0 and random.random() < 0.004:
                self._rnd_wait(*_T_THINK)

    def _load_photo_button_xpaths(self) -> list:
        """
        learn_photo_button.py로 학습된 사진 버튼 XPath를 로드합니다.
        naver_selectors.json이 없거나 photo_button 키가 없으면 빈 리스트 반환.
        """
        import json as _json
        selector_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "naver_selectors.json"
        )
        try:
            if os.path.exists(selector_file):
                with open(selector_file, "r", encoding="utf-8") as f:
                    data = _json.load(f)
                candidates = data.get("photo_button", {}).get("xpath_candidates", [])
                if candidates:
                    self.log(f"  → 학습된 사진 버튼 XPath {len(candidates)}개 로드")
                    return candidates
        except Exception as e:
            self.log(f"  ⚠️ 선택자 파일 로드 실패: {e}")
        return []

    def _random_scroll(self, small: bool = True) -> None:
        """사람처럼 페이지를 자연스럽게 스크롤."""
        amount = random.randint(80, 250) if small else random.randint(300, 700)
        direction = random.choice([1, 1, -1])   # 주로 아래 방향
        self.driver.execute_script(f"window.scrollBy(0, {amount * direction});")
        self._rnd_wait(0.4, 1.0)

    def _dismiss_all_popups(self) -> None:
        """
        화면에 표시된 모든 팝업·모달·레이어를 닫습니다.
        발행 버튼 클릭 전후, 태그 입력 전 등 주요 시점마다 호출합니다.
        """
        # 1. ESC 키로 1차 닫기
        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            self._rnd_wait(0.3, 0.5)
        except Exception:
            pass

        # 2. CSS 선택자 기반 닫기 버튼 클릭
        close_css = [
            ".se-popup-button-cancel",
            ".se-help-popup-close-button",
            ".se-popup-close-button",
            ".se-popup-close",
            "button.se-close",
            ".layer_close",
            ".btn_close",
            ".ico_close",
            "[class*='popup'] button[class*='close']",
            "[class*='modal'] button[class*='close']",
            "[class*='layer'] button[class*='close']",
            "button[aria-label='닫기']",
            "button[title='닫기']",
        ]
        for sel in close_css:
            try:
                for el in self.driver.find_elements(By.CSS_SELECTOR, sel):
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        self._rnd_wait(0.2, 0.4)
            except Exception:
                pass

        # 3. XPath 기반 닫기/취소 버튼 클릭
        close_xpaths = [
            "//button[normalize-space(.)='닫기']",
            "//button[normalize-space(.)='취소']",
            "//a[normalize-space(.)='닫기']",
            "//button[contains(@class,'close') and not(contains(@class,'btn_publish'))]",
        ]
        for xp in close_xpaths:
            try:
                for el in self.driver.find_elements(By.XPATH, xp):
                    if el.is_displayed():
                        self.driver.execute_script("arguments[0].click();", el)
                        self._rnd_wait(0.2, 0.4)
                        break
            except Exception:
                pass

        # 4. JS로 알려진 팝업 버튼 강제 클릭
        try:
            self.driver.execute_script("""
                ['.se-popup-button-cancel', '.se-help-popup-close-button',
                 '.se-popup-close', '.layer_close', '.btn_close']
                .forEach(function(sel) {
                    document.querySelectorAll(sel).forEach(function(el) {
                        if (el.offsetParent !== null) el.click();
                    });
                });
            """)
            self._rnd_wait(0.3, 0.5)
        except Exception:
            pass

    def _restore_editor_focus(self) -> None:
        """
        이미지 삽입 뒤 유실된 iframe 컨텍스트와 에디터 커서를 복구합니다.
        _write_rich_content가 이미지 세그먼트 처리 직후 호출합니다.
        """
        # 1. default_content로 빠져나온 뒤 에디터 프레임 재진입
        try:
            self.driver.switch_to.default_content()
        except Exception:
            pass

        frame = getattr(self, "_editor_frame", None)
        if frame is not None:
            try:
                self.driver.switch_to.frame(frame)
            except Exception:
                try:
                    self.driver.switch_to.frame("mainFrame")
                except Exception:
                    pass
        else:
            try:
                self.driver.switch_to.frame("mainFrame")
            except Exception:
                pass

        # 2. 에디터 본문 영역 클릭으로 커서 포커스 재설정
        try:
            body = self.driver.find_element(
                By.CSS_SELECTOR, ".se-content, .se-document, #content"
            )
            self.driver.execute_script(
                "arguments[0].click(); arguments[0].focus();", body
            )
            self._rnd_wait(0.5, 1.0)
        except Exception:
            pass

    def _close_any_open_dialog(self) -> None:
        """
        OS 파일 열기 창이 열려 있으면 Escape로 강제 닫습니다.
        이미지 삽입 성공/실패와 무관하게 항상 호출해 창이 열린 채
        포스터가 에디터에 타이핑하는 충돌을 방지합니다.
        """
        try:
            import pyautogui
            pyautogui.press('escape')
            self._rnd_wait(0.4, 0.7)
            pyautogui.press('escape')   # 혹시 2중 모달이면 한 번 더
            self._rnd_wait(0.3, 0.5)
        except Exception:
            pass
        # 브라우저 레벨 모달도 닫기
        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            self._rnd_wait(0.2, 0.4)
        except Exception:
            pass

    def _find_and_use_file_input(self, abs_path: str) -> bool:
        """
        DOM 내 숨겨진 <input type="file"> 엘리먼트에 직접 파일 경로를 전달합니다.
        OS 파일 열기 창이 전혀 열리지 않으므로 가장 안정적인 업로드 방법입니다.
        """
        xpaths = [
            "//input[@type='file']",
            "//input[@type='file' and contains(@accept,'image')]",
        ]
        for context_fn in [lambda: None, lambda: self.driver.switch_to.default_content()]:
            try:
                context_fn()
            except Exception:
                pass
            for xp in xpaths:
                els = self.driver.find_elements(By.XPATH, xp)
                for el in els:
                    try:
                        # CSS로 숨겨진 input도 접근 가능하게 만든 뒤 경로 전달
                        self.driver.execute_script(
                            "arguments[0].style.display='block';"
                            "arguments[0].style.visibility='visible';"
                            "arguments[0].style.opacity='1';",
                            el,
                        )
                        el.send_keys(abs_path)
                        self._rnd_wait(4.0, 6.0)
                        return True
                    except Exception:
                        pass
        return False

    def _insert_image_at_cursor(self, img_path: str) -> bool:
        """
        커서 위치에 이미지를 삽입합니다.

        삽입 전략 (순서대로 시도):
        1. 사진 버튼 클릭 → '내 PC' 모달 → DOM file input에 send_keys (OS 창 없음)
        2. 최후 수단: pyautogui OS 다이얼로그 조작
        어떤 경우에도 finally에서 OS 창을 닫아 에디터 제어권을 반드시 회복함.
        """
        try:
            import pyautogui as _pag
            _pag_ok = True
        except ImportError:
            _pag_ok = False

        abs_path = os.path.abspath(img_path)

        if not os.path.exists(abs_path):
            self.log(f"  ⚠️ 이미지 파일 없음, 건너뜀: {abs_path}")
            return False

        fname = os.path.basename(abs_path)

        # ── 사진 버튼 탐색 ────────────────────────────────────────────
        learned_xpaths = self._load_photo_button_xpaths()
        default_xpaths = [
            "//button[contains(@class,'se-toolbar-item-photo')]",
            "//button[contains(@class,'se-btn-image')]",
            "//button[@title='사진' or @aria-label='사진']",
            "//button[contains(@title,'사진')]",
            "//button[contains(@aria-label,'사진')]",
            "//button[@data-name='image']",
            "//button[@data-name='photo']",
        ]
        photo_btn = None
        for in_default in [False, True]:
            if in_default:
                self.driver.switch_to.default_content()
            for xp in (learned_xpaths + default_xpaths):
                for el in self.driver.find_elements(By.XPATH, xp):
                    try:
                        if el.is_displayed():
                            photo_btn = el
                            break
                    except Exception:
                        pass
                if photo_btn:
                    break
            if photo_btn:
                break

        if not photo_btn:
            self.log(f"  ⚠️ 사진 버튼 미발견 — 건너뜀: {fname}")
            return False

        # ── 전략 전체를 하나의 try/finally로 감싸 창 닫기를 보장 ─────
        _dialog_may_be_open = False
        try:
            # ── 전략 1: 버튼 클릭 → file input 직접 send_keys (OS 창 없음) ─
            self.driver.execute_script("arguments[0].click();", photo_btn)
            self._rnd_wait(1.2, 2.0)

            _clicked_pc = False
            for pc_xp in [
                "//button[contains(.,'PC에서')]",
                "//button[contains(.,'내 PC')]",
                "//*[contains(text(),'내 PC에서')]",
            ]:
                for pc_btn in self.driver.find_elements(By.XPATH, pc_xp):
                    try:
                        if pc_btn.is_displayed():
                            self._human_click(pc_btn)
                            self._rnd_wait(0.8, 1.5)
                            _clicked_pc = True
                            break
                    except Exception:
                        pass
                if _clicked_pc:
                    break

            if _clicked_pc:
                _dialog_may_be_open = True   # OS 창이 열렸을 수 있음

            # OS 창을 무시하고 DOM file input에 직접 경로 전달
            if self._find_and_use_file_input(abs_path):
                _dialog_may_be_open = False
                self.log(f"  → 이미지 삽입 완료 (file input 직접 전달): {fname}")
                return True

            self.log(f"  ⚠️ file input 직접 전달 실패 → 전략 2(pyautogui) 시도: {fname}")

            # ── 전략 2 (최후 수단): pyautogui OS 다이얼로그 조작 ──────
            if _pag_ok:
                if not _dialog_may_be_open:
                    self.driver.execute_script("arguments[0].click();", photo_btn)
                    self._rnd_wait(1.5, 2.5)
                    for pc_xp in ["//button[contains(.,'PC에서')]", "//button[contains(.,'내 PC')]"]:
                        for pc_btn in self.driver.find_elements(By.XPATH, pc_xp):
                            try:
                                if pc_btn.is_displayed():
                                    self._human_click(pc_btn)
                                    self._rnd_wait(1.2, 2.0)
                                    break
                            except Exception:
                                pass
                    _dialog_may_be_open = True

                pyperclip.copy(abs_path)
                self._rnd_wait(0.8, 1.2)
                _pag.hotkey('ctrl', 'a')
                self._rnd_wait(0.2, 0.3)
                _pag.hotkey('ctrl', 'v')
                self._rnd_wait(0.4, 0.6)
                _pag.press('enter')
                self._rnd_wait(4.0, 6.0)
                _dialog_may_be_open = False
                self.log(f"  → 이미지 삽입 완료 (pyautogui): {fname}")
                return True

        except Exception as e:
            self.log(f"  ⚠️ 이미지 삽입 예외: {e}")

        finally:
            # OS 파일 열기 창이 열린 채 남아있으면 반드시 Escape로 닫음
            if _dialog_may_be_open:
                self.log(f"  ⚠️ 파일 열기 창 강제 닫기 → 포스팅 계속: {fname}")
                self._close_any_open_dialog()

        return False

    # ── 로그인 ──────────────────────────────────────────────────────
    def login(self, naver_id: str, naver_pw: str) -> bool:
        """네이버 로그인. 쿠키 세션이 유효하면 재로그인 생략."""
        try:
            self.log("🌐 브라우저를 시작합니다...")
            self._init_driver()

            self.log("🔍 저장된 로그인 세션 확인 중...")
            if self._load_cookies_and_check():
                return True

            self.log("🔑 네이버 로그인 페이지로 이동 중...")
            self.driver.get(self.NAVER_LOGIN_URL)
            self._rnd_wait(*_T_PAGE)

            # 아이디: 한 글자씩 타이핑
            self.log("📝 아이디 입력 중...")
            id_field = self.driver.find_element(By.ID, "id")
            self.driver.execute_script("arguments[0].value = '';", id_field)
            self._human_click(id_field)
            self._rnd_wait(0.5, 1.0)
            self._human_type(naver_id, 0.08, 0.18)
            self._rnd_wait(0.5, 1.0)

            # 비밀번호: 한 글자씩 타이핑
            self.log("🔒 비밀번호 입력 중...")
            pw_field = self.driver.find_element(By.ID, "pw")
            self.driver.execute_script("arguments[0].value = '';", pw_field)
            self._human_click(pw_field)
            self._rnd_wait(0.4, 0.9)
            self._human_type(naver_pw, 0.07, 0.16)
            self._rnd_wait(0.5, 1.0)

            # ── 로그인 상태 유지 체크박스 ──────────────────────────────
            self.log("  로그인 상태 유지 체크 중...")
            _checked = False
            # 방법 1: id="keep" 체크박스 직접 클릭
            for cb_selector, lbl_selector in [
                (By.ID, "keep"),
                (By.CSS_SELECTOR, "input[name='keep']"),
                (By.CSS_SELECTOR, "input.keep_check"),
                (By.XPATH, "//input[@type='checkbox' and contains(@id,'keep')]"),
            ]:
                try:
                    cb = self.driver.find_element(cb_selector, lbl_selector)
                    if not cb.is_selected():
                        # label 클릭이 더 안정적
                        try:
                            lbl = self.driver.find_element(
                                By.XPATH,
                                f"//label[@for='{cb.get_attribute('id')}']"
                            )
                            self._human_click(lbl)
                        except Exception:
                            self._human_click(cb)
                        self._rnd_wait(0.3, 0.6)
                    # JS로 체크 상태 강제 확인
                    if not cb.is_selected():
                        self.driver.execute_script(
                            "arguments[0].checked = true;"
                            "arguments[0].dispatchEvent(new Event('change',{bubbles:true}));",
                            cb
                        )
                        self._rnd_wait(0.2, 0.4)
                    _checked = True
                    self.log("  → 로그인 상태 유지 체크 완료")
                    break
                except Exception:
                    continue

            if not _checked:
                # 방법 2: label 텍스트로 탐색
                try:
                    lbl = self.driver.find_element(
                        By.XPATH,
                        "//*[contains(text(),'로그인 상태 유지') or "
                        "contains(text(),'로그인상태유지') or "
                        "contains(text(),'keep')]"
                    )
                    self._human_click(lbl)
                    self._rnd_wait(0.3, 0.6)
                    self.log("  → 로그인 상태 유지 label 클릭 완료")
                    _checked = True
                except Exception:
                    self.log("  ⚠️ 로그인 상태 유지 체크박스를 찾지 못했습니다 (계속 진행)")

            # 로그인 버튼 클릭
            # 예전에는 By.ID "log.login" 하나만 봤는데, 네이버가 로그인 페이지 마크업을
            # 바꾸면서 그 id 가 사라져 NoSuchElementException 으로 로그인이 전부 실패했다.
            # 후보를 순서대로 시도한다. 클릭은 기존대로 _human_click 을 쓰므로
            # 사람같은 클릭 동작(스텔스)은 그대로 유지된다.
            self.log("✅ 로그인 버튼 클릭...")
            # 2026-08 실측 기준 네이버 로그인 페이지 구조:
            #   #loginBtn_row / #loginBtn_column  (class="btn_done", 텍스트 "로그인")
            #   레이아웃에 따라 둘 중 하나만 보인다. type 은 submit 이 아니라 button 이다.
            #   같은 btn_done 클래스로 "패스키 로그인" 버튼도 있으니 텍스트로 걸러야 한다.
            _btn_candidates = [
                (By.ID, "loginBtn_row"),
                (By.ID, "loginBtn_column"),
                (By.CSS_SELECTOR, "button.btn_done"),
                (By.ID, "log.login"),                      # 구버전 페이지 대비
                (By.XPATH, "//button[normalize-space()='로그인']"),
                (By.CSS_SELECTOR, "form button[type='submit']"),
            ]
            login_btn = None
            for _by, _sel in _btn_candidates:
                try:
                    # find_element(단수)는 첫 매치만 준다. 첫 매치가 숨어 있으면
                    # 그 셀렉터를 통째로 포기하게 되므로 반드시 복수로 훑는다.
                    for _el in self.driver.find_elements(_by, _sel):
                        _txt = (_el.text or "").strip()
                        if "패스키" in _txt:
                            continue
                        if _el.is_displayed() and _el.is_enabled():
                            login_btn = _el
                            self.log(f"  → 로그인 버튼 찾음: {_sel} ({_txt or 'no-text'})")
                            break
                    if login_btn is not None:
                        break
                except Exception:
                    continue
            if login_btn is None:
                self.log("  ❌ 로그인 버튼을 찾지 못했습니다. 네이버 로그인 페이지 구조가 또 바뀐 듯합니다.")
                raise RuntimeError("로그인 버튼 후보 전부 실패")
            self._human_click(login_btn)
            self._rnd_wait(*_T_PAGE)

            # 2차 인증 대기
            self._rnd_wait(1.5, 2.5)
            if "nid.naver.com" in self.driver.current_url:
                # 60초는 사람이 기기등록·캡차를 처리하기에 빠듯하다(실제로 놓쳤다).
                # 환경변수로 조절 가능하게 두고 기본 3분.
                _auth_wait = int(os.environ.get("NAVER_AUTH_WAIT", "180"))
                self.log(f"⚠️ 추가 인증이 필요합니다. 브라우저 창에서 직접 인증해주세요! "
                         f"(최대 {_auth_wait}초 대기)")
                try:
                    _deadline = time.time() + _auth_wait
                    while time.time() < _deadline:
                        if "nid.naver.com" not in self.driver.current_url:
                            break
                        _left = int(_deadline - time.time())
                        if _left % 30 == 0 and _left > 0:
                            self.log(f"    인증 대기 중... {_left}초 남음")
                        time.sleep(1)
                    if "nid.naver.com" in self.driver.current_url:
                        raise TimeoutError("인증 대기 시간 초과")
                    self.log("✅ 인증 완료!")
                except Exception:
                    self.log(f"❌ {_auth_wait}초 경과: 로그인 실패 (아이디/비밀번호 또는 인증 미완료)")
                    return False

            self._save_cookies()
            self.log("✅ 로그인 성공! 쿠키 저장 완료 - 다음부터는 자동 세션 복원")
            return True

        except Exception as e:
            self.log(f"❌ 로그인 오류: {type(e).__name__} - {e}")
            return False

    # ── 글쓰기 ──────────────────────────────────────────────────────
    def _wait_file_dialog(self, timeout_s: float = 8) -> bool:
        """윈도우 '열기' 파일 선택 창이 실제로 떴는지 확인한다.

        왜 필요한가 — 이 확인 없이 Ctrl+A/Ctrl+V/Enter 를 보내면, 창이 안 떴을 때
        그 키가 브라우저 에디터로 들어간다. Ctrl+A 가 본문을 전부 선택한 상태에서
        경로가 붙여넣기돼 **본문이 통째로 사라지고 로컬 경로가 공개된다**.
        키를 보내기 전에 창의 존재를 반드시 확인해야 한다.
        """
        try:
            import pygetwindow as gw
        except ImportError:
            self.log("  ⚠️ pygetwindow 미설치 — 파일 창 확인 불가, 안전을 위해 건너뜁니다")
            return False

        import time as _t
        # 윈도우 파일 대화상자 제목은 로캘에 따라 다르다
        names = ("열기", "Open", "파일 선택", "업로드할 파일 선택", "Choose File", "File Upload")
        deadline = _t.time() + timeout_s
        while _t.time() < deadline:
            try:
                for w in gw.getAllWindows():
                    t = (w.title or "").strip()
                    if t and any(n.lower() in t.lower() for n in names):
                        try:
                            w.activate()   # 포커스를 확실히 그 창으로 옮긴다
                        except Exception:
                            pass
                        self.log(f"  → 파일 선택 창 확인: '{t[:30]}'")
                        return True
            except Exception:
                pass
            _t.sleep(0.4)
        return False

    def write_post(self, title: str, content: str, _category: str = "",
                   naver_id: str = "", tags: str = "",
                   image_paths: list = None,
                   segments: list = None) -> bool:
        """블로그 글 작성 및 발행.

        Args:
            segments: 편집과장이 변환한 서식 세그먼트 목록.
                      제공 시 Bold/크기/색상을 툴바로 직접 적용하며 타이핑합니다.
                      None이면 content를 일반 텍스트로 타이핑합니다.
        """
        try:
            self.log("📝 글쓰기 페이지로 이동 중...")
            write_url = (f"{self.NAVER_BLOG_WRITE_URL}?blogId={naver_id}"
                         if naver_id else self.NAVER_BLOG_WRITE_URL)
            self.driver.get(write_url)
            self._rnd_wait(*_T_PAGE)

            if "nid.naver.com" in self.driver.current_url:
                self.log("❌ 글쓰기 접근 실패: 세션 만료 또는 캡차 차단")
                return False

            wait = WebDriverWait(self.driver, 30)

            # 팝업 제거 (프레임 탐색 전)
            try:
                self.driver.execute_script(
                    "document.querySelectorAll('.se-popup-button-cancel,"
                    " .se-help-popup-close-button').forEach(el => el.click());"
                )
            except Exception:
                pass

            # ── iframe 탐색 ──────────────────────────────────────────
            self.log("🖼️ 에디터 iframe 탐색 중...")
            target_frame = None
            try:
                target_frame = wait.until(
                    EC.presence_of_element_located((By.ID, "mainFrame"))
                )
                self.driver.switch_to.frame(target_frame)
                self.log("  → mainFrame 진입")
            except Exception:
                self.log("  ⚠️ mainFrame 탐색 실패, 전체 iframe 스캔...")
                self.driver.switch_to.default_content()
                for i, frame in enumerate(self.driver.find_elements(By.TAG_NAME, "iframe")):
                    try:
                        self.driver.switch_to.default_content()
                        self.driver.switch_to.frame(frame)
                        if self.driver.find_elements(
                            By.CSS_SELECTOR,
                            ".se-title-text, .se-content, .se-editor-container"
                        ):
                            target_frame = frame
                            self.log(f"  → {i}번째 iframe에서 에디터 발견")
                            break
                    except Exception:
                        continue

            if not target_frame:
                self.driver.switch_to.default_content()
                if not self.driver.find_elements(
                    By.CSS_SELECTOR, ".se-title-text, .se-content"
                ):
                    self.log("❌ 에디터를 찾지 못했습니다.")
                    return False
                self.log("  → 프레임 없이 에디터 직접 노출 확인")

            # 에디터 프레임 참조 저장 — 이미지 삽입 후 포커스 복구에 활용
            self._editor_frame = target_frame

            self._rnd_wait(1.5, 2.5)

            # 안내 팝업 닫기
            try:
                for btn in self.driver.find_elements(
                    By.CSS_SELECTOR,
                    ".se-popup-button-cancel, .se-help-popup-close-button"
                ):
                    if btn.is_displayed():
                        self._human_click(btn)
                        self._rnd_wait(0.5, 1.0)
            except Exception:
                pass

            # 페이지 살짝 스크롤 (사람처럼 확인하는 척)
            self._random_scroll(small=True)

            # ── 제목 입력 ─────────────────────────────────────────────
            self.log("📌 제목 타이핑 중...")
            try:
                title_area = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".se-title-text, .se-title-input, #title")
                ))
                self._human_click(title_area)
                self._rnd_wait(0.6, 1.2)
                ActionChains(self.driver)\
                    .key_down(Keys.CONTROL).send_keys("a")\
                    .key_up(Keys.CONTROL).send_keys(Keys.BACKSPACE)\
                    .perform()
                self._rnd_wait(0.3, 0.6)
                self._human_type(title, 0.05, 0.14)
                self._rnd_wait(0.5, 1.0)
            except Exception as e:
                self.log(f"  ⚠️ 제목 입력 오류: {type(e).__name__}")
                return False

            # Tab 키로 본문 영역으로 자연스럽게 이동
            ActionChains(self.driver).send_keys(Keys.TAB).perform()
            self._rnd_wait(0.5, 1.0)

            # ── 본문 입력: 세그먼트 서식 방식 또는 일반 타이핑 ────────────
            self.log("📄 본문 입력 중...")
            try:
                body_area = wait.until(EC.element_to_be_clickable(
                    (By.CSS_SELECTOR, ".se-content, .se-document, #content")
                ))
                self._human_click(body_area)
                self._rnd_wait(0.8, 1.5)

                if segments:
                    self.log(f"  → 서식 세그먼트 {len(segments)}개 Rich-text 입력 모드")
                    self._write_rich_content(segments)
                else:
                    # 폴백: 일반 텍스트 타이핑
                    type_body = content.strip()
                    if type_body.startswith("```"):
                        type_body = re.sub(r"^```[a-zA-Z]*\n?", "", type_body)
                        type_body = re.sub(r"\n?```$", "", type_body.strip())
                    self.log(f"  → 총 {len(type_body)}자 일반 타이핑 시작...")
                    self._human_type(type_body)


                self._rnd_wait(0.8, 1.5)
                self.log("  → 본문 입력 완료")
            except Exception as e:
                self.log(f"  ⚠️ 본문 입력 오류: {type(e).__name__} — {e}")

            # ── 이미지 첨부 (segments에 image 세그먼트가 있으면 건너뜀) ────
            _has_inline_images = segments and any(
                s.get("type") == "image" for s in segments
            )
            if image_paths and not _has_inline_images:
                # NAVER_IMG_MODE=input 이면 pyautogui 를 건너뛰고 숨은 파일 입력에 직접 넣는다.
                # OS 파일 창을 거치지 않아 마우스·키보드를 뺏지 않고, 창이 안 떠서 실패하는 문제도 없다.
                _force_input = os.environ.get("NAVER_IMG_MODE", "").lower() == "input"
                try:
                    import pyautogui
                    _pag_ok = not _force_input
                    if _force_input:
                        self.log("  → NAVER_IMG_MODE=input — 파일 입력 직접 주입 방식을 씁니다")
                except ImportError:
                    _pag_ok = False
                    self.log("  ⚠️ pyautogui 미설치 — 'pip install pyautogui' 후 재시도 (fallback 사용)")

                self.log(f"📸 이미지 {len(image_paths)}장 첨부 시작...")

                # ── 학습된 XPath 로드 (최우선 사용) ─────────────────────
                learned_xpaths = self._load_photo_button_xpaths()
                # 기본 후보 XPath (폴백용)
                default_xpaths = [
                    "//button[contains(@class,'se-toolbar-item-photo')]",
                    "//button[contains(@class,'se-btn-image')]",
                    "//button[contains(@class,'__se_btn_photo')]",
                    "//button[@title='사진' or @aria-label='사진']",
                    "//button[contains(@title,'사진')]",
                    "//button[contains(@aria-label,'사진')]",
                    "//button[@data-name='image']",
                    "//button[@data-name='photo']",
                    "//button[.//i[contains(@class,'photo')] or .//span[contains(@class,'photo')]]",
                    "//button[.//svg[contains(@class,'photo')]]",
                ]
                # 학습된 XPath를 앞에 배치
                photo_xpaths = learned_xpaths + default_xpaths

                for img_idx, img_path in enumerate(image_paths):
                    try:
                        # 사진추가 버튼 탐색: 현재 컨텍스트 → default_content
                        photo_btn = None
                        for in_default in [False, True]:
                            if in_default:
                                self.driver.switch_to.default_content()
                            for xp in photo_xpaths:
                                for el in self.driver.find_elements(By.XPATH, xp):
                                    try:
                                        if el.is_displayed():
                                            photo_btn = el
                                            self.log(f"  → 사진 버튼 발견: {xp[:50]}")
                                            break
                                    except Exception:
                                        pass
                                if photo_btn:
                                    break
                            if photo_btn:
                                break

                        if photo_btn and _pag_ok:
                            # 사진추가 버튼 클릭
                            self.driver.execute_script("arguments[0].click();", photo_btn)
                            self.log(f"  → 사진추가 버튼 클릭 ({img_idx+1}번째)")
                            self._rnd_wait(1.5, 2.5)

                            # 브라우저 내 모달 '내 PC에서 찾기' 처리
                            for pc_xp in [
                                "//button[contains(.,'PC에서')]",
                                "//button[contains(.,'내 PC')]",
                                "//*[contains(text(),'내 PC에서')]",
                            ]:
                                clicked_pc = False
                                for pc_btn in self.driver.find_elements(By.XPATH, pc_xp):
                                    try:
                                        if pc_btn.is_displayed():
                                            self._human_click(pc_btn)
                                            self.log("  → '내 PC에서 찾기' 선택")
                                            self._rnd_wait(1.2, 2.0)
                                            clicked_pc = True
                                            break
                                    except Exception:
                                        pass
                                if clicked_pc:
                                    break

                            # OS 파일 다이얼로그: 경로 붙여넣기 후 열기
                            #
                            # ⚠️ 창이 떴는지 반드시 먼저 확인한다 (2026-08-25 사고).
                            # 예전에는 확인 없이 Ctrl+A → Ctrl+V → Enter 를 보냈는데,
                            # 파일 선택 창이 안 뜨면 그 키가 에디터 본문으로 들어간다.
                            # Ctrl+A 가 본문 전체를 선택한 뒤 경로가 덮어써져 **글 본문이 통째로
                            # 날아가고 로컬 경로가 공개**됐다. 실제로 그렇게 발행된 글이 있었다.
                            _bulk_dialog_open = True
                            try:
                                if not self._wait_file_dialog(timeout_s=8):
                                    _bulk_dialog_open = False
                                    self.log(f"  ⚠️ 이미지 {img_idx+1}: 파일 선택 창이 뜨지 않아 건너뜁니다"
                                             " (키 입력을 보내지 않았습니다)")
                                    continue
                                abs_img_path = os.path.abspath(img_path)
                                pyperclip.copy(abs_img_path)
                                self._rnd_wait(0.5, 0.8)
                                pyautogui.hotkey('ctrl', 'a')
                                self._rnd_wait(0.2, 0.4)
                                pyautogui.hotkey('ctrl', 'v')
                                self._rnd_wait(0.4, 0.7)
                                pyautogui.press('enter')
                                self._rnd_wait(4.0, 7.0)   # 업로드 완료 대기
                                _bulk_dialog_open = False
                                self.log(f"  → 이미지 {img_idx+1}장 전송 (업로드 여부는 발행 후 확인 필요)")
                            except Exception as _de:
                                self.log(f"  ⚠️ 이미지 {img_idx+1} 다이얼로그 입력 실패: {_de}")
                            finally:
                                if _bulk_dialog_open:
                                    self.log(f"  ⚠️ 파일 열기 창 강제 닫기 (이미지 {img_idx+1} 건너뜀)")
                                    self._close_any_open_dialog()

                        else:
                            # Fallback: 숨겨진 file input에 경로 직접 전달
                            self.log("  ⚠️ 사진추가 버튼 미발견 또는 pyautogui 없음 — 파일 입력창 직접 접근")
                            try:
                                self.driver.switch_to.frame("mainFrame")
                            except Exception:
                                pass
                            file_input = wait.until(
                                EC.presence_of_element_located(
                                    (By.XPATH, "//input[@type='file']")
                                )
                            )
                            self.driver.execute_script(
                                "arguments[0].style.display='block';"
                                " arguments[0].style.opacity='1';",
                                file_input,
                            )
                            file_input.send_keys(img_path)
                            self._rnd_wait(3.5, 7.0)
                            ActionChains(self.driver).send_keys(Keys.ENTER).perform()
                            self._wait(1.0)
                            self.log(f"  → 이미지 {img_idx+1}장 업로드 완료 (fallback)")

                    except Exception as e:
                        self.log(f"  ⚠️ 이미지 {img_idx+1} 첨부 오류: {type(e).__name__}")

            # iframe 밖으로
            try:
                self.driver.switch_to.default_content()
                self._rnd_wait(0.8, 1.5)
            except Exception:
                pass

            # 내용 확인하듯 스크롤
            self._random_scroll(small=False)
            self._rnd_wait(0.8, 1.5)

            # ── 발행 전 팝업 전체 닫기 ────────────────────────────────
            self.log("🧹 발행 전 팝업 닫기...")
            self._dismiss_all_popups()

            # ── 1차 발행 버튼 ────────────────────────────────────────
            self.log("🚀 발행 버튼 클릭...")
            try:
                def _hybrid_safe_click(btn_element):
                    """팝업 등 방해요소가 있을 때 일반 클릭 -> 강제 클릭으로 이어지는 안전 클릭"""
                    try:
                        self._human_click(btn_element)
                        return True
                    except Exception as e:
                        self.log(f"  → 일반 클릭 실패({type(e).__name__}), 팝업 무시 후 강제 클릭 시도")
                        # 화면을 가리는 팝업을 닫기 위해 ESC 시도
                        ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                        self._rnd_wait(0.2, 0.5)
                        # JS 강제 클릭 폴백
                        self.driver.execute_script("arguments[0].click();", btn_element)
                        return True

                publish_xpath = (
                    "//button[contains(.,'발행')] | //a[contains(.,'발행')]"
                    " | //*[contains(@class,'btn_publish')]"
                )
                btns = wait.until(
                    EC.presence_of_all_elements_located((By.XPATH, publish_xpath))
                )
                clicked = False
                for btn in btns:
                    if btn.is_displayed():
                        _hybrid_safe_click(btn)
                        clicked = True
                        break
                if not clicked and btns:
                    _hybrid_safe_click(btns[0])
                # 발행 패널이 슬라이드 인 되기까지 대기 (닫지 않음)
                self._rnd_wait(2.0, 3.0)

                # ── 카테고리 선택 (실패해도 발행은 계속) ──────────────
                if _category:
                    self._select_category(_category)
                    self._rnd_wait(0.5, 1.0)

                # ── 태그 입력 ──────────────────────────────────────
                def _clean_tag(t: str) -> str:
                    """태그 정제: 한글·영문·숫자·언더스코어만 남깁니다."""
                    return re.sub(r'[^\w가-힣]', '', t.strip())

                def _is_valid_tag(t: str) -> bool:
                    """
                    유효한 태그인지 검사합니다.
                    - 순수 CSS 색상 헥스코드 제거 (3~6자리 16진수만으로 구성)
                    - 숫자만으로 구성된 태그 제거
                    - 한국어 포함 시 최소 2자 이상
                    - 영문만일 때 최소 3자 이상 (단순 코드값 방지)
                    """
                    if not t:
                        return False
                    # 순수 16진수 색상코드 제거 (예: 333, ddd, 2C3E50, e6f7ff)
                    if re.fullmatch(r'[0-9a-fA-F]{3,6}', t):
                        return False
                    # 순수 숫자 제거
                    if re.fullmatch(r'\d+', t):
                        return False
                    # 한국어 포함 → 최소 2자
                    if re.search(r'[가-힣]', t):
                        return len(t) >= 2
                    # 영문+숫자만 → 최소 3자 이상, 의미있는 단어
                    return len(t) >= 3

                # ── 태그 수집 ──────────────────────────────────────────────
                # tags 파라미터(편집과장 제공)에서만 수집
                # content에서 #xxx 추출은 CSS 색상 오염 위험으로 제거
                raw_tags = [t.strip() for t in tags.split(",") if t.strip()]

                seen = set()
                tag_list = []
                for t in raw_tags:
                    cleaned = _clean_tag(t)
                    if cleaned and cleaned not in seen and _is_valid_tag(cleaned):
                        seen.add(cleaned)
                        tag_list.append(cleaned)

                if tag_list:
                    self.log(f"🏷️ 태그 입력 중... ({', '.join(tag_list[:30])})")
                    try:
                        tag_input = wait.until(EC.presence_of_element_located((By.XPATH,
                            "//input[contains(@placeholder,'태그 입력')"
                            " or contains(@title,'태그 입력')]"
                            " | //textarea[contains(@placeholder,'태그 입력')]"
                            " | //*[contains(@class,'tag_input')"
                            " or contains(@class,'tagInput')]//input"
                        )))
                        _tag_xpath = (
                            "//input[contains(@placeholder,'태그 입력')"
                            " or contains(@title,'태그 입력')]"
                            " | //textarea[contains(@placeholder,'태그 입력')]"
                            " | //*[contains(@class,'tag_input')"
                            " or contains(@class,'tagInput')]//input"
                        )
                        for t in tag_list[:30]:
                            # ENTER 후 Naver가 DOM을 재생성하므로 매 루프마다 재탐색
                            tag_input = wait.until(EC.presence_of_element_located(
                                (By.XPATH, _tag_xpath)
                            ))
                            self.driver.execute_script("arguments[0].focus();", tag_input)
                            self._human_type(t, 0.06, 0.14)
                            tag_input.send_keys(Keys.ENTER)
                            self._rnd_wait(0.25, 0.55)
                    except Exception as e:
                        self.log(f"  ⚠️ 태그 입력 실패: {type(e).__name__}")

                self._rnd_wait(0.8, 1.5)

                # ── 최종 발행 확인 팝업 ──────────────────────────
                self.log("🚀 최종 발행 확인...")
                try:
                    confirm_xpath = (
                        "//*[contains(@class,'btn_confirm')]"
                        " | //button[contains(.,'발행')]"
                    )
                    confirm_btns = wait.until(
                        EC.presence_of_all_elements_located((By.XPATH, confirm_xpath))
                    )
                    for btn in reversed(confirm_btns):
                        if btn.is_displayed():
                            self.driver.execute_script("arguments[0].click();", btn)
                            break
                    self._rnd_wait(1.5, 3.0)
                except Exception:
                    pass

            except Exception as e:
                self.log(f"  ⚠️ 발행 오류: {type(e).__name__}")
                return False

            self.log("🎉 포스팅 완료!")
            return True

        except Exception as e:
            self.log(f"❌ 글쓰기 오류: {type(e).__name__}")
            try:
                self.log(f"🔍 오류 당시 URL: {self.driver.current_url}")
            except Exception:
                pass
            return False

    # ── Rich-text 서식 조작 메서드 ──────────────────────────────────────

    def _select_category(self, name: str) -> bool:
        """
        발행 패널에서 블로그 카테고리를 고른다.

        원래 write_post 의 _category 인자는 선언만 되어 있고 어디에서도 쓰이지 않았다
        (밑줄 접두사가 그 표시였다). 그래서 모든 글이 기본 카테고리로 발행됐다.

        실패해도 절대 예외를 올리지 않는다 — 카테고리 하나 때문에 글 발행 자체가
        무산되는 편이 손해가 크다. 실패 시 기본 카테고리로 그냥 발행된다.
        패널 구조를 모를 때를 대비해 보이는 후보를 로그로 남긴다.
        """
        if not name:
            return False
        try:
            self.log(f"🗂️ 카테고리 선택 시도: {name}")

            # ── 1) 카테고리 드롭다운 열기 ─────────────────────────────
            # 실측(2026-08): 발행 패널의 카테고리 선택은
            #   button[class*="selectbox_button"]  (현재 선택된 카테고리명이 버튼 텍스트)
            # 이다. class 에 'category' 가 든 요소는 '글감'(se-flayer-unified-category-*)
            # 이라 이걸 눌러 봐야 카테고리 목록이 안 나온다 — 이 함정에 세 번 빠졌다.
            opener_xpaths = [
                "//button[contains(@class,'selectbox_button')]",
                "//button[contains(@class,'selectbox')]",
                "//button[contains(.,'카테고리') and not(contains(@class,'unified'))]",
            ]
            opened = False
            for xp in opener_xpaths:
                for el in self.driver.find_elements(By.XPATH, xp):
                    try:
                        txt = (el.text or "").strip()
                        if not el.is_displayed() or "글감" in txt:
                            continue
                        # 마우스 클릭(_human_click)으로 열면 포커스가 옮겨가며
                        # 목록이 곧바로 닫혀 li 가 하나도 안 잡혔다. JS 클릭이 안정적이다.
                        self.driver.execute_script("arguments[0].click();", el)
                        time.sleep(2.0)                    # 목록이 그려질 시간
                        opened = True
                        self.log(f"  → 드롭다운 열기 (현재값: {txt[:20]})")
                        break
                    except Exception:
                        continue
                if opened:
                    break
            if not opened:
                self.log("  ⚠️ 카테고리 드롭다운을 찾지 못했습니다")
                return False

            # ── 2) 목록에서 항목을 찾아 클릭 ──────────────────────────
            # 실측한 드롭다운 구조:
            #   ul[class*="list__"] > li[class*="option__"]
            #     · 최상위 항목  → 텍스트가 이름 그대로        ("제품소개")
            #     · 하위 항목    → "하위 카테고리\n<이름>"      ("하위 카테고리\nVIDEO")
            #
            # '하위 카테고리'는 접힘 토글이 아니라 '이건 하위 항목이다'를 알리는 라벨이다.
            # 이걸 토글로 오해해 전부 클릭했다가 엉뚱한 카테고리가 선택된 적이 있다.
            # 따라서 각 li 의 '마지막 줄'을 실제 이름으로 보고 비교한다.
            result = self.driver.execute_script("""
                const target = arguments[0];
                const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
                // 항목 태그가 li 인지 div 인지 확실치 않다. 목록 컨테이너를 먼저 찾고
                // 그 '직계 자식'을 항목으로 본다 — 태그에 의존하지 않는 방법이다.
                let items = [...document.querySelectorAll('[class*="option__"]')].filter(vis);
                if (items.length < 3) {
                    const cont = [...document.querySelectorAll('[class*="list__"]')]
                        .filter(vis)
                        .sort((a, b) => b.children.length - a.children.length)[0];
                    if (cont) items = [...cont.children].filter(vis);
                }
                const names = [];
                let hit = null;
                for (const li of items) {
                    const lines = (li.innerText || '').trim().split('\\n')
                                    .map(s => s.replace(/\\u00a0/g, ' ').trim()).filter(Boolean);
                    if (!lines.length) continue;
                    const nm = lines[lines.length - 1];      // 마지막 줄이 실제 이름
                    names.push(nm);
                    if (nm === target && !hit) hit = li;
                }
                if (hit) {
                    const c = hit.querySelector('a, button, label, span') || hit;
                    c.click();
                    return {ok: true, names: names};
                }
                return {ok: false, names: names};
            """, name)

            found = result.get("names") or []
            self.log(f"  목록 {len(found)}개: {', '.join(found[:24])}")

            if result.get("ok"):
                self._rnd_wait(0.8, 1.3)
                cur = self.driver.execute_script("""
                    const b = [...document.querySelectorAll('button[class*="selectbox_button"]')]
                      .find(e => e.offsetParent !== null);
                    return b ? (b.innerText||'').trim().split('\\n').pop() : '';""")
                self.log(f"  ✅ 카테고리 '{name}' 선택 완료 (현재값: {cur[:20]})")
                return True

            self.log(f"  ⚠️ '{name}' 항목이 목록에 없습니다 — 기본 카테고리로 발행됩니다")
            return False
        except Exception as e:
            self.log(f"  ⚠️ 카테고리 선택 중 오류(무시하고 계속): {type(e).__name__}")
            return False

    def _bold_on(self) -> None:
        """굵게 ON — Ctrl+B (iframe 내부 커서에서도 확실히 동작)"""
        try:
            ActionChains(self.driver).key_down(Keys.CONTROL).send_keys('b').key_up(Keys.CONTROL).perform()
            self._rnd_wait(0.1, 0.2)
        except Exception as e:
            self.log(f"  ⚠️ 굵게 설정 실패: {e}")

    def _bold_off(self) -> None:
        """굵게 OFF — Ctrl+B 토글"""
        self._bold_on()

    def _set_font_size(self, size: str) -> None:
        """
        글자 크기 설정.
        툴바는 iframe 바깥에 있으므로 default_content로 나가서 클릭 후 iframe으로 복귀.

        후보 셀렉터를 여러 개 훑으므로 암묵 대기를 끄고 돈다 — 켜 두면
        빗나간 셀렉터마다 10초씩 붙는다(_no_implicit_wait 주석 참고).
        """
        with self._no_implicit_wait():
            self._set_font_size_inner(size)

    def _set_font_size_inner(self, size: str) -> None:
        try:
            # 1. iframe 밖으로 나가기
            self.driver.switch_to.default_content()
            self._rnd_wait(0.2, 0.3)

            # 2. 글자 크기 드롭다운 열기 (부모 프레임 기준)
            size_btn_xpaths = [
                "//button[@data-name='fontSize']",
                "//*[contains(@class,'se-toolbar-item-font-size')]//button",
                "//button[contains(@class,'font-size')]",
            ]
            opened = False
            for xp in size_btn_xpaths:
                els = self.driver.find_elements(By.XPATH, xp)
                for el in els:
                    try:
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            opened = True
                            break
                    except Exception:
                        pass
                if opened:
                    break

            if not opened:
                # 폴백: execCommand 방식 (일부 환경에서 동작)
                self.log(f"  ⚠️ 글자크기 드롭다운 미발견 — execCommand 폴백 시도")
                self._restore_editor_focus()
                self.driver.execute_script(
                    f"document.execCommand('fontSize', false, '{size}');"
                )
                return

            self._rnd_wait(0.3, 0.5)

            # 3. 크기 옵션 선택
            option_xpaths = [
                f"//li[contains(@class,'se-list-item')]//button[normalize-space(.)='{size}']",
                f"//button[contains(@class,'font-size') and normalize-space(.)='{size}']",
                f"//*[contains(@class,'size-list')]//button[normalize-space(.)='{size}']",
            ]
            selected = False
            for xp in option_xpaths:
                els = self.driver.find_elements(By.XPATH, xp)
                for el in els:
                    try:
                        if el.is_displayed():
                            self.driver.execute_script("arguments[0].click();", el)
                            selected = True
                            break
                    except Exception:
                        pass
                if selected:
                    break

            if not selected:
                # 드롭다운 닫기
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()

            self._rnd_wait(0.2, 0.3)

        except Exception as e:
            self.log(f"  ⚠️ 글자크기 {size} 설정 실패: {e}")
        finally:
            # 4. 반드시 iframe으로 복귀
            try:
                frame = getattr(self, "_editor_frame", None)
                if frame:
                    self.driver.switch_to.frame(frame)
                else:
                    self.driver.switch_to.frame("mainFrame")
            except Exception:
                pass

    def _color_current_line(self, hex_color: str) -> None:
        """
        방금 입력한 줄을 선택해서 글자색을 입힌다.

        Shift+Home 으로 줄 전체를 잡고, 그때 뜨는 property toolbar 에서 색을 고른다.
        선택이 없으면 색상 버튼이 화면에 아예 없다 — 그게 예전 구현이 실패한 이유다.
        마지막에 End 로 선택을 풀어 다음 입력에 영향을 주지 않게 한다.

        색상 툴바도 후보 셀렉터를 훑으므로 암묵 대기를 끈다. 이 경로는 아직
        한 번도 성공한 적이 없어서(색이 안 먹는다) **매번 전부 빗나간다** —
        즉 대기 시간을 고스란히 다 물고 있었다.
        """
        with self._no_implicit_wait():
            self._color_current_line_inner(hex_color)

    def _color_current_line_inner(self, hex_color: str) -> None:
        try:
            ActionChains(self.driver).key_down(Keys.SHIFT).send_keys(Keys.HOME)\
                .key_up(Keys.SHIFT).perform()
            self._rnd_wait(0.4, 0.7)
            self._set_font_color(hex_color)
        except Exception as e:
            self.log(f"  ⚠️ 글자색 적용 실패: {str(e)[:70]}")
        finally:
            try:
                ActionChains(self.driver).send_keys(Keys.END).perform()
                self._rnd_wait(0.2, 0.4)
            except Exception:
                pass

    def _set_font_color(self, hex_color: str) -> None:
        """
        글자색을 지정한다.

        예전 구현은 hex 입력창(`input.se-hex-input` 등) 하나만 추측해서 찾다가
        늘 "컬러 팔레트 입력창 미발견" 으로 실패했다. 색이 한 번도 적용된 적이 없다.
        이제 세 갈래로 시도하고, 전부 실패하면 **그때 화면에 뭐가 있었는지 로그로 남긴다**.
        추측을 반복하지 않으려면 실패가 정보를 남겨야 한다.
        """
        with self._no_implicit_wait():
            self._set_font_color_inner(hex_color)

    def _set_font_color_inner(self, hex_color: str) -> None:
        want = hex_color.lstrip("#").upper()
        try:
            # ── 팔레트 열기 ──
            opened = self.driver.execute_script("""
                const b = document.querySelector("button[data-name='fontColor']")
                       || document.querySelector("button[class*='font-color']")
                       || [...document.querySelectorAll('button')]
                            .find(x => /글자색|색상/.test(x.getAttribute('aria-label')||x.title||''));
                if (!b) return false;
                const sib = b.parentElement ? b.parentElement.querySelectorAll('button') : [];
                (sib.length > 1 ? sib[sib.length-1] : b).click();
                return true;
            """)
            if not opened:
                raise Exception("글자색 버튼을 찾지 못함")
            self._rnd_wait(0.6, 1.0)

            # ── 1) hex 입력창 ──
            done = self.driver.execute_script("""
                const want = arguments[0];
                const inp = [...document.querySelectorAll('input')]
                    .filter(i => i.offsetParent !== null)
                    .find(i => /hex|색상|color/i.test(
                        (i.className||'') + ' ' + (i.placeholder||'') + ' ' + (i.name||'')));
                if (!inp) return false;
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(inp, want);
                inp.dispatchEvent(new Event('input', {bubbles:true}));
                inp.dispatchEvent(new KeyboardEvent('keydown', {key:'Enter', bubbles:true}));
                inp.dispatchEvent(new Event('change', {bubbles:true}));
                return true;
            """, want)

            # ── 2) 팔레트에서 같은 색 스와치 누르기 ──
            if not done:
                done = self.driver.execute_script("""
                    const want = arguments[0];
                    const hex = c => {
                        const m = (c||'').match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                        if (!m) return '';
                        return [1,2,3].map(i => (+m[i]).toString(16).padStart(2,'0'))
                                      .join('').toUpperCase();
                    };
                    const el = [...document.querySelectorAll('button,li,span,a')]
                        .filter(e => e.offsetParent !== null)
                        .find(e => hex(getComputedStyle(e).backgroundColor) === want);
                    if (!el) return false;
                    el.click();
                    return true;
                """, want)

            if done:
                self._rnd_wait(0.4, 0.7)
                return

            # ── 실패했으면 화면 구조를 남긴다 ──
            dump = self.driver.execute_script("""
                const vis = e => e.offsetParent !== null;
                return {
                  inputs: [...document.querySelectorAll('input')].filter(vis).slice(0,8)
                    .map(i => ({cls:(i.className||'').toString().slice(0,40),
                                ph:i.placeholder||'', type:i.type})),
                  colorish: [...document.querySelectorAll('[class*="color"],[class*="Color"]')]
                    .filter(vis).slice(0,8)
                    .map(e => ({tag:e.tagName, cls:(e.className||'').toString().slice(0,50)}))
                };
            """)
            self.log(f"  ⚠️ 글자색 {hex_color} 미적용 — 화면 구조: {json.dumps(dump, ensure_ascii=False)[:300]}")
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()

        except Exception as e:
            self.log(f"  ⚠️ 글자색 {hex_color} 설정 실패: {str(e)[:80]}")
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            except Exception:
                pass

    def _reset_font_color(self) -> None:
        """글자색을 기본(검정)으로 초기화."""
        try:
            # 1. 팔레트 열기
            self.driver.execute_script("""
                var btn = document.querySelector("button[data-name='fontColor']");
                if(btn && btn.parentElement) {
                    var btns = btn.parentElement.querySelectorAll("button");
                    if(btns.length > 0) {
                        btns[btns.length - 1].click();
                    }
                }
            """)
            self._rnd_wait(0.5, 0.8)
            
            # 2. 기본색 버튼 클릭
            resets = self.driver.find_elements(
                By.CSS_SELECTOR,
                ".se-color-reset, button[title='기본색'], button.se-reset-button"
            )
            if resets and resets[0].is_displayed():
                self.driver.execute_script("arguments[0].click();", resets[0])
                self._rnd_wait(0.2, 0.4)
            else:
                raise Exception("기본색 버튼 미발견")
                
        except Exception as e:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            self._set_font_color("#000000")



    def _insert_divider(self) -> None:
        """네이버 에디터에 구분선 삽입 (─ 문자 30개로 대체)."""
        try:
            divider_text = "─" * 28
            self._human_type(divider_text, 0.01, 0.02)
            ActionChains(self.driver).send_keys(Keys.RETURN).perform()
            self._rnd_wait(*_T_PARA)
        except Exception as e:
            self.log(f"  ⚠️ 구분선 삽입 실패: {type(e).__name__}")

    def _insert_quote_box(self, text: str) -> None:
        """
        네이버 SmartEditor ONE 인용구 버튼을 클릭하고 텍스트를 입력한다.
        툴바는 iframe 바깥에 있으므로 default_content → 버튼 클릭 → iframe 복귀 순서로 진행.
        인용구 버튼을 찾지 못하면 ─ 구분선으로 감싼 텍스트 박스로 폴백한다.
        """
        _QUOTE_XPATHS = [
            "//button[@data-name='blockquote']",
            "//button[contains(@class,'se-toolbar-item-quotation')]",
            "//button[contains(@class,'se-toolbar-item-blockquote')]",
            "//button[@title='인용구']",
            "//button[@aria-label='인용구']",
            "//button[contains(@title,'인용')]",
            "//button[contains(@aria-label,'인용')]",
        ]
        try:
            # 1. 툴바(iframe 바깥)로 이동
            self.driver.switch_to.default_content()
            self._rnd_wait(0.2, 0.3)

            # 2. 인용구 버튼 탐색
            btn = None
            for xp in _QUOTE_XPATHS:
                els = self.driver.find_elements(By.XPATH, xp)
                if els:
                    btn = els[0]
                    break

            if btn:
                btn.click()
                self._rnd_wait(0.3, 0.5)
                self.log("  📌 인용구 버튼 클릭 완료")
            else:
                self.log("  ⚠️ 인용구 버튼 미발견 → 텍스트 박스 폴백")
                raise RuntimeError("인용구 버튼 없음")

            # 3. 에디터 iframe 복귀
            self._restore_editor_focus()

            # 4. 텍스트 입력
            self._human_type(text)

            # 5. 인용구 블록 탈출: 빈 줄 Enter 후 Backspace로 일반 단락 복귀
            ActionChains(self.driver).send_keys(Keys.RETURN).perform()
            self._rnd_wait(0.1, 0.2)
            ActionChains(self.driver).send_keys(Keys.RETURN).perform()
            self._rnd_wait(0.2, 0.4)
            self.log(f"  ✅ 인용구 박스 완료: '{text[:30]}...'")

        except Exception as e:
            # 폴백: ─ 구분선으로 감싼 시각 박스
            self.log(f"  ⚠️ 인용구 실패({type(e).__name__}) → 구분선 박스 폴백")
            try:
                self._restore_editor_focus()
                bar = "─" * 26
                self._human_type(bar, 0.01, 0.02)
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._human_type(text)
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._human_type(bar, 0.01, 0.02)
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._rnd_wait(*_T_PARA)
            except Exception as fe:
                self.log(f"  ⚠️ 폴백도 실패: {type(fe).__name__}")

    def _write_rich_content(self, segments: list) -> None:
        """
        서식 세그먼트 목록을 순서대로 처리하여 네이버 에디터에 입력합니다.

        각 세그먼트별:
          - heading/emphasis → Bold ON + (선택) 크기/색 설정 → 타이핑 → 초기화
          - normal           → 기본 설정으로 타이핑
          - hr               → 구분선 삽입
        """
        current_bold  = False
        current_size  = "14"
        current_color = None  # None = 기본색

        for idx, seg in enumerate(segments):
            seg_type  = seg.get("type", "normal")
            text      = seg.get("text", "").strip()
            bold      = seg.get("bold", False)
            size      = seg.get("size", "14")
            color     = seg.get("color")         # None이면 기본색
            nl_before = seg.get("newline_before", 0)
            nl_after  = seg.get("newline_after",  1)

            # ── 구분선 ────────────────────────────────────────────────
            if seg_type == "hr":
                self._insert_divider()
                continue

            # ── 인용구 박스 ───────────────────────────────────────────
            if seg_type == "quote_box":
                if text:
                    self.log(f"  [{idx+1}/{len(segments)}] 📌 인용구 박스: '{text[:30]}...'")
                    self._insert_quote_box(text)
                continue

            # ── 이미지 삽입 ───────────────────────────────────────────
            if seg_type == "image":
                img_path = seg.get("path", "")
                if not img_path or not os.path.exists(img_path):
                    self.log(f"  [{idx+1}/{len(segments)}] ⚠️ 이미지 파일 없음 — 건너뜀")
                    continue
                visual_label = seg.get("visual_label") or seg.get("visual_type") or seg.get("section") or "이미지"
                self.log(f"  [{idx+1}/{len(segments)}] 📸 이미지 삽입 시도: {visual_label} "
                         f"({os.path.basename(img_path)})")
                ok = self._insert_image_at_cursor(img_path)

                # 이미지 삽입 후 iframe 컨텍스트 + 커서 복구 (성공/실패 무관하게 항상)
                self._restore_editor_focus()

                if ok:
                    # 이미지 뒤 줄바꿈
                    for _ in range(seg.get("newline_after", 1)):
                        ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                        self._rnd_wait(*_T_PARA)
                    self.log(f"  [{idx+1}/{len(segments)}] ✅ 이미지 삽입 완료 → 다음 단락 진행")
                else:
                    self.log(f"  [{idx+1}/{len(segments)}] ⏭️ 이미지 삽입 실패 — 열기 창 닫고 포스팅 계속")
                continue

            if not text:
                continue

            # ── HTML 잔여 태그 제거 + <br> → 줄바꿈 변환 ─────────────
            text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
            text = re.sub(r'<[^>]+>', '', text).strip()
            if not text:
                continue

            # ── 앞 줄바꿈 ─────────────────────────────────────────────
            for _ in range(nl_before):
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._rnd_wait(*_T_PARA)

            # ── 서식 적용 ─────────────────────────────────────────────
            if bold and not current_bold:
                self._bold_on()
                current_bold = True

            if size != current_size:
                self._set_font_size(size)
                current_size = size

            # 색은 '타이핑 뒤 선택해서' 입힌다 — 아래 _human_type 다음을 보라.
            # 미리 지정하는 방식은 한 번도 성공한 적이 없다(아래 주석 참고).

            # ── 텍스트 타이핑 ─────────────────────────────────────────
            preview = text[:25] + ("..." if len(text) > 25 else "")
            self.log(f"  [{idx+1}/{len(segments)}] ✏️  {seg_type}: '{preview}' "
                     f"(bold={bold}, size={size})")
            self._human_type(text)

            # ── 글자색: 방금 친 줄을 선택한 뒤 입힌다 ──────────────────
            # 왜 이 순서인가: 색상 버튼은 'property toolbar' 에 있고, 그 툴바는
            # **텍스트가 선택돼 있을 때만** 나타난다. 그래서 예전처럼 타이핑 전에
            # 색을 지정하려 하면 버튼 자체가 화면에 없어 늘 실패했다
            # (로그에 "컬러 팔레트 입력창 미발견" 이 매번 찍혔고 색이 한 번도 안 먹었다).
            if color:
                self._color_current_line(color)
                current_color = None

            # ── 서식 초기화 (다음 normal 세그먼트를 위해) ──────────────
            if bold and current_bold:
                self._bold_off()
                current_bold = False

            if size != "14":
                self._set_font_size("14")
                current_size = "14"

            # ── 뒤 줄바꿈 ─────────────────────────────────────────────
            for _ in range(nl_after):
                ActionChains(self.driver).send_keys(Keys.RETURN).perform()
                self._rnd_wait(*_T_PARA)

    # ── 종료 ────────────────────────────────────────────────────────
    def close(self) -> None:
        if self.driver:
            try:
                self.driver.quit()
            except Exception:
                pass
            self.driver = None
            self.log("🛑 브라우저 종료")

    def run_full_post(
        self,
        naver_id: str,
        naver_pw: str,
        title: str,
        content: str,
        tags: str = "",
        category: str = "",
        image_paths: list = None,
        segments: list = None,
    ) -> bool:
        """로그인 → 글쓰기 → 태그입력 → 발행 전 과정을 한 번에 실행."""
        try:
            if not self.login(naver_id, naver_pw):
                return False
            return self.write_post(
                title, content, category,
                naver_id=naver_id, tags=tags,
                image_paths=image_paths,
                segments=segments,
            )
        finally:
            self.close()
