"""
WorkerThread - 비동기 자동화를 Qt 스레드에서 실행

PyQt6의 GUI 스레드를 블로킹하지 않고
asyncio 기반 플러그인을 별도 스레드에서 구동합니다.
"""

import asyncio
from typing import List

from PyQt6.QtCore import QThread, pyqtSignal


class WorkerThread(QThread):
    """
    자동화 작업을 별도 스레드에서 실행

    시그널:
        log_message(str, str)   : 로그 메시지, 레벨
        progress(int, int)      : 현재 완료 수, 전체 수
        service_done(str, bool) : 서비스명, 성공 여부
        all_done()              : 전체 완료
    """

    log_message   = pyqtSignal(str, str)
    progress      = pyqtSignal(int, int)
    service_done  = pyqtSignal(str, bool)
    all_done      = pyqtSignal()

    def __init__(
        self,
        services: List[str],
        project_name: str = "",
        youtube_params: dict = None,
    ):
        super().__init__()
        self.services = services
        self.project_name = project_name
        self.youtube_params = youtube_params or {}
        self._stop_flag = False

    def run(self):
        """스레드 진입점 — 새 이벤트 루프에서 실행"""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(self._run_all())
        finally:
            loop.close()

    async def _run_all(self):
        """선택된 서비스 순서대로 실행"""
        total = len(self.services)
        done = 0

        SERVICE_MAP = {
            "anthropic": ("plugins.anthropic_plugin", "AnthropicPlugin"),
            "gemini":    ("plugins.gemini_plugin",    "GeminiPlugin"),
            "openai":    ("plugins.openai_plugin",    "OpenAIPlugin"),
            "github":    ("plugins.github_plugin",    "GitHubPlugin"),
            "aws":       ("plugins.aws_plugin",       "AWSPlugin"),
            "youtube":   ("plugins.youtube_plugin",   "YouTubePlugin"),
        }

        for service in self.services:
            if self._stop_flag:
                self.log_message.emit("⛔ 사용자가 중단했습니다.", "WARNING")
                break

            module_path, class_name = SERVICE_MAP[service]

            try:
                import importlib
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
            except Exception as e:
                self.log_message.emit(f"[{service}] 플러그인 로드 실패: {e}", "ERROR")
                self.service_done.emit(service, False)
                done += 1
                self.progress.emit(done, total)
                continue

            # 진행상황 콜백 → Qt 시그널 연결
            def make_callback(svc):
                def cb(msg, level):
                    self.log_message.emit(f"[{svc.upper()}] {msg}", level)
                return cb

            if service == "youtube":
                plugin = plugin_class(
                    progress_callback=make_callback(service),
                    project_name=self.project_name,
                    **self.youtube_params,
                )
            else:
                plugin = plugin_class(progress_callback=make_callback(service), project_name=self.project_name)

            self.log_message.emit(f"🚀 [{service.upper()}] 자동화 시작...", "INFO")
            result = await plugin.run()

            done += 1
            self.progress.emit(done, total)
            self.service_done.emit(service, result.success)

            if result.success:
                self.log_message.emit(
                    f"✅ [{service.upper()}] 완료 — 키 이름: {result.key_name}", "SUCCESS"
                )
            else:
                self.log_message.emit(
                    f"❌ [{service.upper()}] 실패: {result.error}", "ERROR"
                )

        self.all_done.emit()

    def stop(self):
        """외부에서 중단 요청"""
        self._stop_flag = True
