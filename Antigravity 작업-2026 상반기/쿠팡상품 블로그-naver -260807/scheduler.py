"""
scheduler.py
매일 지정된 시간에 자동으로 네이버 블로그에 글을 포스팅하는 스케줄러 모듈
"""
import threading
import schedule
import time
from datetime import datetime


class BlogScheduler:
    """블로그 자동 포스팅 스케줄러"""

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._is_running = False
        self._job_func = None

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self, post_time: str, job_callback) -> None:
        """
        스케줄러를 시작합니다.
        
        Args:
            post_time: "HH:MM" 형태의 시간 (예: "09:00")
            job_callback: 매일 실행할 함수
        """
        if self._is_running:
            self.stop()

        schedule.clear()
        self._stop_event.clear()
        self._job_func = job_callback

        schedule.every().day.at(post_time).do(job_callback)

        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._is_running = True
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            schedule.run_pending()
            time.sleep(30)
        self._is_running = False

    def stop(self) -> None:
        """스케줄러를 중지합니다."""
        self._stop_event.set()
        schedule.clear()
        self._is_running = False

    def run_now(self) -> None:
        """즉시 예약된 작업을 실행합니다."""
        if self._job_func:
            t = threading.Thread(target=self._job_func, daemon=True)
            t.start()

    def next_run_time(self) -> str:
        """다음 실행 예정 시간을 문자열로 반환합니다."""
        jobs = schedule.get_jobs()
        if jobs:
            next_run = jobs[0].next_run
            if next_run:
                return next_run.strftime("%Y-%m-%d %H:%M")
        return "미설정"
