# ============================================================
#  singleton.py — 같은 프로그램이 두 벌 뜨는 것을 막는 잠금
#
#  왜 필요한가:
#    2026-07-31, service.py 가 두 번 실행되어 감독기 4개·동기화 2개가 떠 있었다.
#    뒤에 뜬 감독기는 포트(8010/8000)를 못 잡아 11시간 동안 154회 재시작을 반복했고,
#    동기화가 2개라 같은 접수 리드를 두 번 등록할 위험이 있었다.
#    → 두 번째 실행은 아예 뜨지 못하게 막는다.
#
#  잠금 방식: OS 파일 잠금(Windows msvcrt / POSIX fcntl).
#    프로세스가 죽으면 OS 가 잠금을 자동 해제하므로 '유령 잠금'이 남지 않는다.
#    (PID 파일만 쓰는 방식은 강제 종료 시 잠금이 영원히 남아 다음 실행을 막는다.)
#
#  사용:
#      import singleton
#      singleton.acquire("service")      # 이미 떠 있으면 AlreadyRunning 예외
# ============================================================
import os
import atexit
from pathlib import Path

_DEFAULT_DIR = Path(__file__).parent / "data" / "locks"


class AlreadyRunning(RuntimeError):
    """이미 같은 이름의 프로세스가 실행 중."""

    def __init__(self, name: str, pid: str):
        self.name = name
        self.pid = pid
        super().__init__(f"{name} 이(가) 이미 실행 중입니다 (pid {pid})")


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


def _pid_path(d: Path, name: str) -> Path:
    return d / f"{name}.pid"


def holder_pid(name: str, lock_dir=None) -> str:
    """지금 잠금을 쥐고 있는 프로세스의 PID(표시용). 모르면 '?'."""
    d = Path(lock_dir) if lock_dir else _DEFAULT_DIR
    try:
        return _pid_path(d, name).read_text(encoding="utf-8").strip() or "?"
    except Exception:
        return "?"


def is_running(name: str, lock_dir=None) -> bool:
    """다른 프로세스가 이 이름으로 실행 중인지 (잠금을 잡아보고 곧바로 놓는다).
    ⚠ 자기 자신이 이미 acquire 한 경우에도 True 가 아니라 False 가 나올 수 있으니
      점검용으로만 쓸 것."""
    d = Path(lock_dir) if lock_dir else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.lock"
    try:
        fh = open(path, "a+")
    except Exception:
        return False
    try:
        if _try_lock(fh):
            _unlock(fh)
            return False
        return True
    finally:
        try:
            fh.close()
        except Exception:
            pass


def acquire(name: str, lock_dir=None):
    """이 이름의 단독 실행권을 잡는다. 이미 떠 있으면 AlreadyRunning.

    잠금은 프로세스가 살아 있는 동안 유지되며, 종료(정상·비정상 모두) 시 OS 가 푼다.
    잠금 파일과 PID 파일을 나눠 쓴다 — 잠금 중인 파일을 truncate 하면 Windows 에서
    잠금 영역이 깨질 수 있기 때문."""
    d = Path(lock_dir) if lock_dir else _DEFAULT_DIR
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.lock"

    fh = open(path, "a+")
    if not _try_lock(fh):
        pid = holder_pid(name, d)
        try:
            fh.close()
        except Exception:
            pass
        raise AlreadyRunning(name, pid)

    # 잠금 확보 후에만 PID 를 남긴다(사람이 보고 확인하는 용도).
    try:
        _pid_path(d, name).write_text(str(os.getpid()), encoding="utf-8")
    except Exception:
        pass

    def _release():
        _unlock(fh)
        try:
            fh.close()
        except Exception:
            pass
        try:
            p = _pid_path(d, name)
            if p.read_text(encoding="utf-8").strip() == str(os.getpid()):
                p.unlink()
        except Exception:
            pass

    atexit.register(_release)
    # 참조를 살려 둬야 GC 가 파일을 닫아 잠금을 풀어버리지 않는다.
    _HELD.append(fh)
    return path


_HELD = []
