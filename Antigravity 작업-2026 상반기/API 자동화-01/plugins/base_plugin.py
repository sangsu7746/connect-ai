"""
BasePlugin - 서비스 플러그인 추상 베이스 클래스

모든 서비스 플러그인은 이 클래스를 상속받아 구현합니다.
공통 기능: 로깅, 에러 핸들링, 진행상황 콜백, 세션 관리
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from loguru import logger

from core.browser_engine import BrowserEngine
from core.session_manager import SessionManager
from core.page_navigator import PageNavigator
from security.key_vault import KeyVault
from security.env_manager import EnvManager


@dataclass
class PluginResult:
    """플러그인 실행 결과"""
    success: bool
    service: str
    key_name: str = ""
    env_updated: bool = False
    error: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class BasePlugin(ABC):
    """
    서비스 플러그인 추상 베이스 클래스
    
    서브클래스 필수 구현:
        - SERVICE_NAME: str
        - CONSOLE_URL: str
        - navigate_to_key_page()
        - create_api_key()
        - verify_key()
    """

    # 서브클래스에서 반드시 설정
    SERVICE_NAME: str = ""
    CONSOLE_URL: str = ""
    ENV_KEY_NAME: str = ""

    def __init__(self, progress_callback: Optional[Callable] = None, project_name: str = ""):
        self.progress_callback = progress_callback or self._default_callback
        self.project_name = project_name
        self._vault = KeyVault()
        self._env_manager = EnvManager()
        self._session_manager = SessionManager()
        self._engine: Optional[BrowserEngine] = None
        self._navigator: Optional[PageNavigator] = None

    # ───────────────────────────── 메인 실행 흐름 ─────────────────────────────

    async def run(self) -> PluginResult:
        """
        전체 자동화 실행 (템플릿 메서드 패턴)
        
        흐름:
            1. 브라우저 시작
            2. 콘솔 페이지로 이동 (세션 복원 또는 수동 로그인)
            3. API Key 생성
            4. 키 추출 및 암호화 저장
            5. .env 업데이트
            6. 연결 테스트
        """
        self._log(f"[{self.SERVICE_NAME.upper()}] 자동화 시작", "INFO")

        engine = BrowserEngine(headless=False)  # 로그인 확인을 위해 헤드풀
        await engine.start()
        self._engine = engine

        try:
            page = await engine.new_page()
            self._navigator = PageNavigator(page)

            # 1. 콘솔로 이동
            self._log("콘솔 페이지로 이동 중...", "INFO")
            await self._navigator.goto(self.CONSOLE_URL)

            # 2. 로그인 확인 (세션 있으면 스킵)
            login_ok = await self._ensure_logged_in(page)
            if not login_ok:
                return PluginResult(
                    success=False,
                    service=self.SERVICE_NAME,
                    error="로그인 실패 또는 타임아웃"
                )

            # 3. API Key 생성 페이지로 이동
            self._log("API Key 생성 페이지로 이동...", "INFO")
            await self.navigate_to_key_page()

            # 4. API Key 생성
            self._log("API Key 생성 중...", "INFO")
            key_name = self._generate_key_name()
            api_key = await self.create_api_key(key_name)

            if not api_key:
                await engine.save_screenshot(page, f"{self.SERVICE_NAME}_error")
                return PluginResult(
                    success=False,
                    service=self.SERVICE_NAME,
                    error="API Key 추출 실패"
                )

            # 5. 암호화 저장
            self._vault.store_key(self.SERVICE_NAME, key_name, api_key)
            self._log(f"API Key 암호화 저장 완료", "SUCCESS")

            # 6. .env 업데이트
            env_updated = self._env_manager.update(
                service=self.SERVICE_NAME,
                api_key=api_key,
                key_name=self.ENV_KEY_NAME
            )

            # 7. 세션 저장
            await engine.save_session(self.SERVICE_NAME)
            self._session_manager.save_session_meta(self.SERVICE_NAME)

            # 8. 연결 테스트
            self._log("API 연결 테스트 중...", "INFO")
            verified = await self.verify_key(api_key)

            if verified:
                self._log("연결 테스트 통과 ✅", "SUCCESS")
            else:
                self._log("연결 테스트 실패 (키는 저장됨)", "WARNING")

            return PluginResult(
                success=True,
                service=self.SERVICE_NAME,
                key_name=key_name,
                env_updated=env_updated,
            )

        except Exception as e:
            logger.exception(f"[{self.SERVICE_NAME}] 예외 발생: {e}")
            if self._navigator:
                try:
                    await engine.save_screenshot(self._navigator.page, f"{self.SERVICE_NAME}_exception")
                except Exception:
                    pass
            return PluginResult(
                success=False,
                service=self.SERVICE_NAME,
                error=str(e)
            )
        finally:
            await engine.stop()

    # ───────────────────────────── 추상 메서드 (서브클래스 구현 필수) ─────────────────────────────

    @abstractmethod
    async def navigate_to_key_page(self):
        """API Key 생성 페이지로 이동"""
        ...

    @abstractmethod
    async def create_api_key(self, key_name: str) -> Optional[str]:
        """
        API Key 생성 및 값 반환
        
        Returns:
            생성된 API Key 문자열, 실패 시 None
        """
        ...

    @abstractmethod
    async def verify_key(self, api_key: str) -> bool:
        """API Key 연결 테스트"""
        ...

    # ───────────────────────────── 공통 유틸 (서브클래스 사용 가능) ─────────────────────────────

    async def _ensure_logged_in(self, page, wait_timeout: int = 120) -> bool:
        """
        로그인 상태 확인 및 대기

        세션이 유효하면 즉시 True 반환.
        로그인 필요 시 사용자가 직접 로그인할 때까지 최대 wait_timeout초 대기.
        """
        await asyncio.sleep(2)  # 페이지 로드 대기

        is_logged_in = await self._check_logged_in()
        if is_logged_in:
            self._log("로그인 세션 확인", "INFO")
            return True

        # 로그인 안내 메시지 (이모지 없이 안전하게)
        self._log(
            f"[{self.SERVICE_NAME.upper()}] 로그인이 필요합니다. 브라우저에서 로그인하세요.",
            "WARNING"
        )

        # GUI / CLI 공용: 브라우저가 열려 있으므로 최대 120초 동안 로그인 대기
        for elapsed in range(0, wait_timeout, 3):
            await asyncio.sleep(3)
            current = await self._navigator.get_current_url()
            is_logged_in = await self._check_logged_in()
            if is_logged_in:
                self._log("로그인 감지!", "SUCCESS")
                return True
            remaining = wait_timeout - elapsed - 3
            if remaining > 0 and elapsed % 15 == 0 and elapsed > 0:
                self._log(f"로그인 대기 중... (남은 시간: {remaining}초) | URL: {current[:60]}", "INFO")

        self._log("로그인 대기 시간 초과", "ERROR")
        return False

    async def _check_logged_in(self) -> bool:
        """로그인 여부 확인 (서브클래스에서 오버라이드 권장)"""
        # 기본 구현: URL에 'login' 또는 'signin'이 없으면 로그인 된 것으로 판단
        current_url = await self._navigator.get_current_url()
        return "login" not in current_url and "signin" not in current_url

    def _generate_key_name(self) -> str:
        """키 이름 생성 — 프로젝트명 지정 시 사용, 없으면 자동 생성"""
        now = datetime.now().strftime("%Y%m%d_%H%M")
        if self.project_name:
            return f"{self.project_name}_{now}"
        return f"auto_{self.SERVICE_NAME}_{now}"

    def _log(self, message: str, level: str = "INFO"):
        """로깅 + 진행상황 콜백"""
        log_fn = {
            "DEBUG":   logger.debug,
            "INFO":    logger.info,
            "WARNING": logger.warning,
            "ERROR":   logger.error,
            "SUCCESS": logger.success,
        }.get(level, logger.info)

        log_fn(f"[{self.SERVICE_NAME.upper()}] {message}")
        self.progress_callback(message, level)

    @staticmethod
    def _default_callback(message: str, level: str):
        """기본 진행상황 콜백 (아무것도 안 함)"""
        pass
