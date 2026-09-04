# ============================================================
#  channels/base.py — 공용 채널 어댑터 인터페이스
#  · 밴드/페북/카카오의 제각각 메서드를 하나의 규격 뒤로 감춘다.
#  · 모든 발행/응답은 dry_run 을 1급 인자로 (기본 True = 안전).
#  · P0-3
# ============================================================
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class PostResult:
    ok: bool
    perm_url: Optional[str] = None       # 게시물 고유 URL(있으면)
    error: Optional[str] = None
    dry_run: bool = False
    # 안전장치가 막은 것(DRY_RUN·일일상한·미로그인·잘못된 대상)인지 여부.
    # 실제 발행 실패(셀렉터 변경·차단·네트워크)와 구분해야 운영자가 헛짚지 않는다.
    blocked: bool = False


@dataclass
class Feedback:
    id: str
    author: str
    text: str
    ts: str                              # ISO 시각
    target: str = ""                     # 어느 채널/방/게시물


@runtime_checkable
class ChannelAdapter(Protocol):
    """세 채널이 모두 구현해야 하는 계약."""
    platform: str

    def login(self, cred: dict) -> bool: ...
    def post(self, target: str, text: str,
             image_path: Optional[str] = None, dry_run: bool = True) -> PostResult: ...
    def read_feedback(self, target: str, since: Optional[str] = None) -> list[Feedback]: ...
    def send_reply(self, target: str, text: str,
                   files: Optional[list] = None, dry_run: bool = True) -> bool: ...


class BaseAdapter:
    """구현 어댑터가 상속하는 공용 도우미 (dry-run 로깅 등)."""
    platform: str = "base"

    def _log_dry(self, action: str, target: str, text: str = "",
                 image_path: Optional[str] = None):
        preview = (text or "").strip().replace("\n", " ")
        if len(preview) > 60:
            preview = preview[:60] + "…"
        img = f" +img={image_path}" if image_path else ""
        print(f"[DRY-RUN][{self.platform}] {action} → {target!r}: {preview}{img}")

    # 지금 발행 중인 post id. 오케스트레이터가 채워 준다.
    # 상한 계산에서 '자기 자신'을 빼기 위한 것(안 빼면 N번째가 늘 막힌다).
    _current_post_id = None

    def _rate_ok(self, channel_id=None) -> bool:
        """오늘 실발행 건수가 상한 미만인지.

        두 가지를 함께 본다.
          · 계정 전체 상한 — 계정이 하루에 광고를 몇 건 뿌렸나(정지의 주된 원인)
          · 채널별 상한   — 같은 방에 반복 게시했나(가장 빨리 걸리는 패턴)
        둘 중 하나라도 넘으면 막는다."""
        import config
        import db
        me = self._current_post_id
        # 계정 상한은 '이 플랫폼' 것만 센다. 밴드와 페북은 서로 다른 계정이라
        # 한쪽 발행이 다른 쪽 몫을 깎을 이유가 없다.
        if db.posts_today(exclude_id=me,
                          platform=self.platform) >= config.DAILY_POST_LIMIT:
            return False
        if channel_id is not None and \
                db.posts_today(channel_id, exclude_id=me) >= config.CHANNEL_DAILY_LIMIT:
            return False
        return True

    def _rate_reason(self, channel_id=None) -> str:
        """막힌 이유를 사람 말로. 대시보드에 그대로 뜬다."""
        import config
        import db
        me = self._current_post_id
        n = db.posts_today(exclude_id=me, platform=self.platform)
        if n >= config.DAILY_POST_LIMIT:
            return (f"{self.platform} 일일 상한 도달({n}/{config.DAILY_POST_LIMIT}건) "
                    f"— 계정 보호")
        if channel_id is not None:
            m = db.posts_today(channel_id, exclude_id=me)
            if m >= config.CHANNEL_DAILY_LIMIT:
                return (f"이 채널 오늘 이미 {m}건 발행"
                        f"(상한 {config.CHANNEL_DAILY_LIMIT}건) — 같은 방 반복 게시 방지")
        return ""

    # 계약 기본 구현(미구현 명시) — 구현 어댑터에서 override
    def login(self, cred: dict) -> bool:
        raise NotImplementedError

    def post(self, target, text, image_path=None, dry_run=True) -> PostResult:
        raise NotImplementedError

    def read_feedback(self, target, since=None) -> list:
        raise NotImplementedError

    def send_reply(self, target, text, files=None, dry_run=True) -> bool:
        raise NotImplementedError
