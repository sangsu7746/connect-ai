"""
YouTubePlugin - YouTube Data API v3 OAuth 2.0 자격증명 자동 발급

자동화 흐름:
  1. Google Cloud Console 로그인
  2. 새 GCP 프로젝트 생성
  3. YouTube Data API v3 활성화
  4. OAuth 동의 화면 구성 (외부 / 테스트 사용자 추가)
  5. OAuth 2.0 클라이언트 ID 생성 (데스크톱 앱)
  6. client_secrets.json 다운로드 → vault/ 저장
  7. InstalledAppFlow로 브라우저 OAuth 인증
  8. 토큰 KeyVault 암호화 저장
"""

import asyncio
import json
from pathlib import Path
from typing import Callable, Optional

from plugins.base_plugin import BasePlugin, PluginResult


SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

_GCP_HOME      = "https://console.cloud.google.com"
_YT_API_URL    = "https://console.cloud.google.com/apis/library/youtube.googleapis.com"
_CONSENT_URL   = "https://console.cloud.google.com/apis/credentials/consent"
_CREDENTIALS   = "https://console.cloud.google.com/apis/credentials"


class YouTubePlugin(BasePlugin):
    """YouTube Data API v3 OAuth 2.0 자격증명 자동 발급 플러그인"""

    SERVICE_NAME = "youtube"
    CONSOLE_URL  = _GCP_HOME
    ENV_KEY_NAME = "YOUTUBE_REFRESH_TOKEN"

    def __init__(
        self,
        progress_callback: Optional[Callable] = None,
        project_name: str = "",
        gcp_project_name: str = "",
        oauth_app_name: str = "",
        user_email: str = "",
    ):
        super().__init__(progress_callback=progress_callback, project_name=project_name)
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d")
        self.gcp_project_name = gcp_project_name or f"APIKeyManager-YT-{ts}"
        self.oauth_app_name   = oauth_app_name   or "APIKeyManager"
        self.user_email       = user_email

    # ── 메인 실행 ────────────────────────────────────────────────────────────
    async def run(self) -> PluginResult:
        self._log("YouTube Data API v3 자동 발급 시작", "INFO")

        from core.browser_engine import BrowserEngine
        engine = BrowserEngine(headless=False)
        await engine.start()
        self._engine = engine

        try:
            page = await engine.new_page()
            from core.page_navigator import PageNavigator
            self._navigator = PageNavigator(page)

            # 1. 로그인
            self._log("Google Cloud Console 접속 — 구글 계정으로 로그인하세요", "INFO")
            await self._navigator.goto(_GCP_HOME)
            login_ok = await self._ensure_logged_in(page, wait_timeout=120)
            if not login_ok:
                return PluginResult(success=False, service=self.SERVICE_NAME, error="Google 로그인 실패")

            # 2. 프로젝트 생성
            self._log(f"GCP 프로젝트 생성: {self.gcp_project_name}", "INFO")
            await self._create_project(page)

            # 3. YouTube Data API v3 활성화
            self._log("YouTube Data API v3 활성화 중...", "INFO")
            await self._enable_youtube_api()

            # 4. OAuth 동의 화면
            self._log("OAuth 동의 화면 구성 중...", "INFO")
            await self._setup_oauth_consent(page)

            # 5. OAuth 클라이언트 ID 생성 + JSON 다운로드
            self._log("OAuth 클라이언트 ID 생성 중...", "INFO")
            secrets_path = await self._create_oauth_client(page)
            if not secrets_path:
                return PluginResult(
                    success=False, service=self.SERVICE_NAME,
                    error="client_secrets.json 다운로드 실패 — vault/ 폴더를 확인하세요"
                )

            # 6. OAuth 인증 → 토큰
            self._log("브라우저에서 Google 계정을 선택하고 권한을 허용하세요...", "INFO")
            token_json = await asyncio.get_event_loop().run_in_executor(
                None, self._run_oauth_flow, secrets_path
            )
            if not token_json:
                return PluginResult(success=False, service=self.SERVICE_NAME, error="OAuth 토큰 획득 실패")

            # 7. KeyVault 저장
            key_name = self._generate_key_name()
            self._vault.store_key(self.SERVICE_NAME, key_name, token_json)
            self._log("YouTube OAuth 토큰 암호화 저장 완료", "SUCCESS")

            # 8. .env 업데이트 (refresh_token)
            token_data = json.loads(token_json)
            env_updated = self._env_manager.update(
                service=self.SERVICE_NAME,
                api_key=token_data.get("refresh_token", ""),
                key_name=self.ENV_KEY_NAME,
            )

            return PluginResult(
                success=True,
                service=self.SERVICE_NAME,
                key_name=key_name,
                env_updated=env_updated,
            )

        except Exception as e:
            self._log(f"예외 발생: {e}", "ERROR")
            import traceback
            self._log(traceback.format_exc(), "DEBUG")
            return PluginResult(success=False, service=self.SERVICE_NAME, error=str(e))
        finally:
            await engine.stop()

    # ── Step 2: GCP 프로젝트 생성 ────────────────────────────────────────────
    async def _create_project(self, page):
        nav = self._navigator
        await nav.goto(_GCP_HOME)
        await nav.random_delay(2000, 3000)

        # 프로젝트 선택 버튼 클릭
        for sel in [
            "[jsname='wQNmvb']",
            "button[aria-label*='프로젝트']",
            "button[aria-label*='project']",
            ".project-selector",
            "#cloud-console-header button:first-child",
        ]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(1500, 2500)

        # 새 프로젝트
        for sel in [
            "button:has-text('새 프로젝트')",
            "a:has-text('새 프로젝트')",
            "button:has-text('NEW PROJECT')",
            "a:has-text('NEW PROJECT')",
        ]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(2000, 3000)

        # 프로젝트 이름 입력
        for sel in [
            "input#p-name",
            "input[id*='project-name']",
            "input[formcontrolname='name']",
            "input[placeholder*='My Project']",
        ]:
            try:
                if await nav.wait_for_selector(sel, timeout=5000):
                    elem = page.locator(sel).first
                    await elem.triple_click()
                    await elem.fill(self.gcp_project_name)
                    self._log(f"프로젝트 이름 입력: {self.gcp_project_name}", "DEBUG")
                    break
            except Exception:
                continue

        await nav.random_delay(800, 1200)

        # 만들기
        for sel in ["button:has-text('만들기')", "button:has-text('CREATE')"]:
            if await nav.click(sel, retry=False):
                break

        self._log("프로젝트 생성 완료 대기 중... (최대 30초)", "INFO")
        await nav.random_delay(8000, 12000)

        # 알림에서 프로젝트 선택
        for _ in range(6):
            for sel in [
                f"a:has-text('{self.gcp_project_name}')",
                "a:has-text('프로젝트 선택')",
                "a:has-text('SELECT PROJECT')",
                "button:has-text('SELECT PROJECT')",
            ]:
                if await nav.click(sel, retry=False):
                    self._log("생성된 프로젝트 선택 완료", "SUCCESS")
                    await nav.random_delay(2000, 3000)
                    return
            await nav.random_delay(3000, 4000)

    # ── Step 3: YouTube Data API v3 활성화 ──────────────────────────────────
    async def _enable_youtube_api(self):
        nav = self._navigator
        await nav.goto(_YT_API_URL)
        await nav.random_delay(3000, 5000)

        # 이미 활성화 여부 확인
        already = await nav.execute_script("""
            return document.body.innerText.includes('API 사용 중지') ||
                   document.body.innerText.includes('DISABLE') ||
                   document.body.innerText.includes('Disable API');
        """)
        if already:
            self._log("YouTube Data API v3 이미 활성화됨", "INFO")
            return

        for sel in [
            "button:has-text('사용')",
            "button:has-text('ENABLE')",
            "button:has-text('Enable')",
        ]:
            if await nav.click(sel, retry=False):
                self._log("YouTube Data API v3 활성화 완료", "SUCCESS")
                await nav.random_delay(4000, 6000)
                return

        self._log("YouTube API 활성화 버튼을 찾지 못했습니다 — 수동 확인 필요", "WARNING")

    # ── Step 4: OAuth 동의 화면 구성 ─────────────────────────────────────────
    async def _setup_oauth_consent(self, page):
        nav = self._navigator
        await nav.goto(_CONSENT_URL)
        await nav.random_delay(3000, 4000)

        # 이미 설정된 경우
        already = await nav.execute_script("""
            return document.body.innerText.includes('앱 수정') ||
                   document.body.innerText.includes('EDIT APP') ||
                   document.body.innerText.includes('Edit App');
        """)
        if already:
            self._log("OAuth 동의 화면 이미 구성됨 — 건너뜀", "INFO")
            return

        # 외부(External) 선택
        for sel in [
            "mat-radio-button[value='EXTERNAL']",
            "input[value='EXTERNAL']",
            "label:has-text('외부')",
            "label:has-text('External')",
        ]:
            if await nav.click(sel, retry=False):
                self._log("사용자 유형: 외부(External) 선택", "DEBUG")
                break
        await nav.random_delay(800, 1200)

        for sel in ["button:has-text('만들기')", "button:has-text('CREATE')"]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(2500, 3500)

        # 앱 이름
        for sel in [
            "input#app-name",
            "input[formcontrolname='applicationName']",
            "input[aria-label*='App name']",
            "input[aria-label*='앱 이름']",
        ]:
            try:
                if await nav.wait_for_selector(sel, timeout=5000):
                    elem = page.locator(sel).first
                    await elem.triple_click()
                    await elem.fill(self.oauth_app_name)
                    self._log(f"앱 이름 입력: {self.oauth_app_name}", "DEBUG")
                    break
            except Exception:
                continue

        await nav.random_delay(500, 1000)

        # 사용자 지원 이메일 선택
        for sel in [
            "mat-select[formcontrolname='userSupportEmail']",
            "[formcontrolname='userSupportEmail']",
        ]:
            if await nav.click(sel, retry=False):
                await nav.random_delay(800, 1200)
                await nav.click("mat-option:first-child", retry=False)
                break

        # 개발자 연락처 이메일
        if self.user_email:
            await nav.random_delay(500, 1000)
            for sel in [
                "input[formcontrolname='developerEmail']",
                "input[type='email']",
            ]:
                try:
                    if await nav.wait_for_selector(sel, timeout=3000):
                        elem = page.locator(sel).last
                        await elem.fill(self.user_email)
                        break
                except Exception:
                    continue

        # 저장 후 계속 (앱 정보)
        await nav.random_delay(800, 1200)
        for sel in ["button:has-text('저장 후 계속')", "button:has-text('SAVE AND CONTINUE')"]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(2500, 3500)

        # 범위 — 저장 후 계속
        for sel in ["button:has-text('저장 후 계속')", "button:has-text('SAVE AND CONTINUE')"]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(2500, 3500)

        # 테스트 사용자 추가
        for sel in [
            "button:has-text('ADD USERS')",
            "button:has-text('사용자 추가')",
            "button:has-text('+ Add Users')",
        ]:
            if await nav.click(sel, retry=False):
                await nav.random_delay(1000, 1500)
                if self.user_email:
                    for input_sel in [
                        "textarea[aria-label*='이메일']",
                        "input[aria-label*='이메일']",
                        "textarea",
                    ]:
                        try:
                            if await nav.wait_for_selector(input_sel, timeout=3000):
                                await page.locator(input_sel).first.fill(self.user_email)
                                break
                        except Exception:
                            continue
                    await nav.random_delay(500, 800)
                    for s in ["button:has-text('추가')", "button:has-text('ADD')"]:
                        if await nav.click(s, retry=False):
                            break
                break

        await nav.random_delay(1000, 1500)
        # 저장 후 계속 (테스트 사용자)
        for sel in ["button:has-text('저장 후 계속')", "button:has-text('SAVE AND CONTINUE')"]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(1500, 2500)
        self._log("OAuth 동의 화면 설정 완료", "SUCCESS")

    # ── Step 5: OAuth 클라이언트 ID 생성 + JSON 다운로드 ────────────────────
    async def _create_oauth_client(self, page) -> Optional[Path]:
        nav = self._navigator
        download_dir = Path("vault")
        download_dir.mkdir(parents=True, exist_ok=True)

        await nav.goto(_CREDENTIALS)
        await nav.random_delay(3000, 4000)

        # + 자격 증명 만들기
        for sel in [
            "button:has-text('자격 증명 만들기')",
            "button:has-text('CREATE CREDENTIALS')",
        ]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(1000, 1500)

        # OAuth 클라이언트 ID
        for sel in [
            "a:has-text('OAuth 클라이언트 ID')",
            "span:has-text('OAuth 클라이언트 ID')",
            "a:has-text('OAuth client ID')",
            "span:has-text('OAuth client ID')",
        ]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(2500, 3500)

        # 데스크톱 앱 선택
        for sel in [
            "mat-select[formcontrolname='applicationType']",
            "mat-select[aria-label*='Application type']",
            "mat-select[aria-label*='애플리케이션 유형']",
        ]:
            if await nav.click(sel, retry=False):
                await nav.random_delay(800, 1200)
                for opt in [
                    "mat-option:has-text('데스크톱 앱')",
                    "mat-option:has-text('Desktop app')",
                    "mat-option:has-text('Desktop App')",
                ]:
                    if await nav.click(opt, retry=False):
                        break
                break
        await nav.random_delay(800, 1200)

        # 클라이언트 이름
        client_name = f"{self.oauth_app_name}-Desktop"
        for sel in [
            "input[formcontrolname='name']",
            "input[aria-label*='이름']",
            "input[aria-label*='Name']",
        ]:
            try:
                if await nav.wait_for_selector(sel, timeout=3000):
                    elem = page.locator(sel).first
                    await elem.triple_click()
                    await elem.fill(client_name)
                    break
            except Exception:
                continue
        await nav.random_delay(800, 1200)

        # 만들기
        for sel in ["button:has-text('만들기')", "button:has-text('CREATE')"]:
            if await nav.click(sel, retry=False):
                break
        await nav.random_delay(3000, 4000)

        # JSON 다운로드 (팝업에서 바로)
        save_path = download_dir / "youtube_client_secrets.json"
        try:
            async with page.expect_download(timeout=12000) as dl_info:
                for sel in [
                    "button:has-text('JSON 다운로드')",
                    "a:has-text('JSON 다운로드')",
                    "button:has-text('DOWNLOAD JSON')",
                    "a[aria-label*='JSON']",
                ]:
                    if await nav.click(sel, retry=False):
                        break
            dl = await dl_info.value
            await dl.save_as(str(save_path))
            self._log(f"client_secrets.json 저장 완료: {save_path}", "SUCCESS")
            # 팝업 닫기
            for sel in ["button:has-text('확인')", "button:has-text('OK')", "button:has-text('닫기')"]:
                await nav.click(sel, retry=False)
            return save_path
        except Exception as e:
            self._log(f"팝업 다운로드 실패 ({e}), 목록에서 재시도...", "WARNING")

        # 폴백: 자격 증명 목록 → 다운로드 아이콘
        for sel in ["button:has-text('확인')", "button:has-text('OK')", "button:has-text('닫기')"]:
            await nav.click(sel, retry=False)
        await nav.goto(_CREDENTIALS)
        await nav.random_delay(2000, 3000)
        try:
            async with page.expect_download(timeout=10000) as dl_info:
                for sel in [
                    "a[aria-label*='다운로드']",
                    "button[aria-label*='다운로드']",
                    "a[title*='Download']",
                    "mat-icon:has-text('file_download')",
                ]:
                    if await nav.click(sel, retry=False):
                        break
            dl = await dl_info.value
            await dl.save_as(str(save_path))
            self._log(f"client_secrets.json 저장 완료 (폴백): {save_path}", "SUCCESS")
            return save_path
        except Exception as e2:
            self._log(f"JSON 다운로드 최종 실패: {e2}", "ERROR")
            return None

    # ── Step 6: OAuth 인증 흐름 ──────────────────────────────────────────────
    def _run_oauth_flow(self, secrets_path: Path) -> Optional[str]:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            credentials = flow.run_local_server(port=0, open_browser=True)
            token_data = {
                "token":         credentials.token,
                "refresh_token": credentials.refresh_token,
                "token_uri":     credentials.token_uri,
                "client_id":     credentials.client_id,
                "client_secret": credentials.client_secret,
                "scopes":        list(credentials.scopes or SCOPES),
            }
            self._log("OAuth 토큰 획득 완료", "SUCCESS")
            return json.dumps(token_data)
        except Exception as e:
            self._log(f"OAuth 흐름 오류: {e}", "ERROR")
            return None

    # ── BasePlugin 추상 메서드 ────────────────────────────────────────────────
    async def navigate_to_key_page(self): pass
    async def create_api_key(self, key_name: str) -> Optional[str]: return None
    async def verify_key(self, api_key: str) -> bool: return True

    async def _check_logged_in(self) -> bool:
        url = await self._navigator.get_current_url()
        if not url:
            return False
        logged_out = ["accounts.google.com", "ServiceLogin", "oauth2/auth", "/signin"]
        return not any(p in url for p in logged_out) and "console.cloud.google.com" in url
