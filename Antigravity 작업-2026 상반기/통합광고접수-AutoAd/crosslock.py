# ============================================================
#  crosslock.py — 프로세스 사이의 배타 잠금 (기다렸다가 잡는다)
#
#  왜 필요한가:
#    밴드·페이스북 발행 엔진은 본문을 **클립보드로** 붙여넣는다.
#      band_automator.py:885   pyperclip.copy(text) → send_keys(CTRL+V)
#      facebook_automator.py:889  같은 방식
#    클립보드는 머신에 하나뿐이다. 두 파이프라인을 동시에 돌리면
#    A 가 복사한 직후 B 가 덮어쓰고, A 는 B 의 내용을 붙여넣는다.
#    → 엉뚱한 방에 엉뚱한 글이 올라가고 되돌릴 수 없다.
#
#    더 나쁜 경우: 밴드 로그인은 **비밀번호**를 클립보드에 복사한다
#    (band_automator.py:302). 그 순간 페북 쪽이 붙여넣으면
#    공개 그룹 글에 비밀번호가 실린다.
#
#  orchestrator 의 _PUBLISH_LOCK 은 threading.RLock 이라 프로세스 안에서만
#  유효하다. 파이프라인을 따로 띄우면 서로를 전혀 막지 못한다.
#
#  잠금 방식: singleton.py 와 같은 OS 파일 잠금.
#    프로세스가 죽으면 OS 가 자동으로 풀어 준다 — 유령 잠금이 남지 않는다.
#    singleton 은 '이미 있으면 즉시 실패'지만, 여기는 '차례를 기다린다'.
#
#  사용:
#      import crosslock
#      with crosslock.hold("publish"):     # 클립보드를 쓰는 구간만 감싼다
#          ...
#  ⚠ 감싸는 구간을 최소로 유지할 것. 발행 간격 대기(90~300초)까지 넣으면
#    다른 플랫폼이 그 시간 내내 놀게 된다.
# ============================================================
import os
import time
from pathlib import Path
from contextlib import contextmanager

_DIR = Path(__file__).parent / "data" / "locks"


class LockTimeout(RuntimeError):
    """제한 시간 안에 잠금을 못 잡았다."""


if os.name == "nt":
    import msvcrt

    def _try_lock(fh) -> bool:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fh):
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fh) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fh):
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


@contextmanager
def hold(name: str = "publish", timeout: float = 900.0, poll: float = 0.3):
    """차례가 올 때까지 기다렸다가 잠금을 잡는다.

    timeout 을 넘기면 LockTimeout. 호출부는 이걸 '발행하지 않음'으로
    처리해야 한다 — 잠금 없이 진행하면 막으려던 사고가 그대로 난다.
    기본 900초는 상대 파이프라인이 로그인(캡차 대기 최대 600초)을 하는
    경우까지 견디도록 잡은 값이다.
    """
    _DIR.mkdir(parents=True, exist_ok=True)
    path = _DIR / f"{name}.crosslock"
    # ⚠ 'a' 로 연다. 'w' 는 파일을 비우는데, 다른 프로세스가 잠근 영역을
    #   건드려 잠금이 깨질 수 있다(singleton.py 에서 같은 문제를 겪었다).
    fh = open(path, "a+")
    deadline = time.time() + max(0.0, timeout)
    got = False
    try:
        while True:
            if _try_lock(fh):
                got = True
                break
            if time.time() >= deadline:
                raise LockTimeout(
                    f"'{name}' 잠금을 {timeout:.0f}초 안에 잡지 못했습니다 — "
                    f"다른 발행 파이프라인이 아직 돌고 있습니다")
            time.sleep(poll)
        yield
    finally:
        if got:
            _unlock(fh)
        try:
            fh.close()
        except Exception:
            pass
