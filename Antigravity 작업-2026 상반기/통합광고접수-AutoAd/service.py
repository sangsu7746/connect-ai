# ============================================================
#  service.py — 상시 구동 감독기 (supervisor)
#  PC를 켜면 아래 3개가 자동으로 뜨고, 죽으면 다시 살린다.
#    1) AutoAd 서버   : 접수 API · 승인 콘솔 · 대시보드 · 예약 스케줄러 (127.0.0.1:8010)
#    2) 대출앱 서버   : 접수 종착점 /api/intake/register            (127.0.0.1:8000)
#    3) 클라우드 동기화: Firestore 수신함 → 대출앱 등록 (cloud_sync --watch)
#
#  ⚠ 발행은 여기서 하지 않는다. 광고 발행은 승인 콘솔에서 사람이 승인해야 나간다.
#  ⚠ 두 서버 모두 127.0.0.1 고정 — 외부 노출 금지(무인증 + 개인정보).
#
#  중복 실행 방어 (2026-07-31 사고 후 추가)
#    · 감독기는 singleton 잠금으로 한 벌만 뜬다. 두 번째 실행은 안내 후 즉시 종료.
#    · 포트를 남이 이미 쓰고 있으면 기동을 시도하지 않는다.
#      (이전엔 여기서 무한 재시도해 11시간 동안 154회 재시작 루프에 빠졌다)
#    · 한 서비스가 연속 5회 실패하면 재시작을 포기하고 로그로 사람을 부른다.
#
#  사용법
#    python service.py            상시 구동(포그라운드)
#    python service.py --status   지금 떠 있는지 점검
#    python service.py --once     한 번만 기동 시도하고 종료(설치 검증용)
#    python service.py --install  Windows 작업 스케줄러에 등록(로그온 시 자동 실행)
#    python service.py --uninstall
# ============================================================
import os
import sys
import io
import time
import signal
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

import config
import singleton

BASE = Path(__file__).parent
LOG_DIR = config.DATA_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

TASK_NAME = "AutoAd"
PY = sys.executable
# 콘솔 창이 뜨지 않게 pythonw 가 있으면 사용
PYW = str(Path(PY).with_name("pythonw.exe"))

RESTART_BACKOFF = [5, 15, 30, 60, 120]   # 연속 실패 시 대기(초)
MAX_FAILS = 5            # 연속 이만큼 실패하면 잠시 손을 뗀다
HALT_COOLDOWN = 1800     # 그 뒤 30분 쉬었다가 다시 한 번 시도한다(영구 포기 금지)
STARTUP_GRACE = 90       # 기동 직후 이 시간 동안은 헬스체크로 죽이지 않는다
HEALTH_STRIKES = 2       # 연속 이만큼 응답 없어야 재시작(일시적 끊김에 안 죽게)
EXIT_ALREADY_RUNNING = 3  # 자식이 '중복이라 비켰다'고 알리는 코드 (cloud_sync 와 약속)
LOG_MAX_BYTES = 5 * 1024 * 1024
LOG_KEEP = 3             # {name}.1.log ~ {name}.3.log

# 자식 프로세스가 한글을 cp949 로 뱉어 로그가 깨지던 문제를 막는다(2026-07-31 확인).
# PYTHONUNBUFFERED 가 없으면 파일로 리다이렉트될 때 블록 버퍼링이 걸려
# sync 로그가 11시간 동안 빈 파일로 남는다.
CHILD_ENV = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")


def _services() -> list:
    loan_dir = Path(config.KAKAO_PROJECT_DIR)
    svcs = [
        {
            "name": "autoad",
            "desc": "AutoAd 서버(접수·승인·대시보드·스케줄러)",
            "cwd": BASE,
            "cmd": [PY, "-m", "uvicorn", "app:app",
                    "--host", "127.0.0.1", "--port", "8010", "--log-level", "warning"],
            "health": "http://127.0.0.1:8010/",
            "port": 8010,
        },
        {
            "name": "sync",
            "desc": "클라우드 수신함 동기화",
            "cwd": BASE,
            "cmd": [PY, "cloud_sync.py", "--watch", "--interval", "180"],
            "health": None,          # 폴링 루프 — 프로세스 생존으로 판단
            "port": None,            # 포트를 안 쓴다
            "lock": "cloud_sync",    # 대신 이 잠금으로 중복 여부를 판단한다
        },
    ]
    # 대출앱은 있을 때만 (없으면 접수 등록이 안 되므로 경고)
    if (loan_dir / "app.py").exists():
        svcs.insert(1, {
            "name": "loanapp",
            "desc": "대출앱 서버(접수 종착점)",
            "cwd": loan_dir,
            "cmd": [PY, "-m", "uvicorn", "app:app",
                    "--host", "127.0.0.1", "--port", "8000", "--log-level", "warning"],
            "health": "http://127.0.0.1:8000/api/loans",
            "port": 8000,
        })
    return svcs


def _rotate(path: Path):
    """로그가 5MB 를 넘으면 세대별로 밀어낸다(최대 3세대 보관)."""
    try:
        if not path.exists() or path.stat().st_size < LOG_MAX_BYTES:
            return
        for i in range(LOG_KEEP - 1, 0, -1):
            src = path.with_suffix(f".{i}.log")
            dst = path.with_suffix(f".{i + 1}.log")
            if src.exists():
                if dst.exists():
                    dst.unlink()
                src.rename(dst)
        first = path.with_suffix(".1.log")
        if first.exists():
            first.unlink()
        path.rename(first)
    except Exception:
        pass          # 로그 정리 실패가 서비스를 멈춰선 안 된다


def _log(msg: str):
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        p = LOG_DIR / "service.log"
        _rotate(p)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _alive(url: str, timeout: float = 2.0) -> bool:
    try:
        import requests
        return requests.get(url, timeout=timeout).status_code < 500
    except Exception:
        return False


def _port_busy(port: int) -> bool:
    """127.0.0.1:port 를 누군가 이미 듣고 있는가."""
    if not port:
        return False
    import socket
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.6)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def _occupied(s: dict) -> str:
    """이 서비스를 이미 다른 프로세스가 돌리고 있으면 그 사유, 아니면 빈 문자열.

    포트를 쓰는 서비스는 포트로, cloud_sync 처럼 포트가 없는 서비스는 잠금으로 판단한다.
    (잠금 검사가 없으면 sync 는 이 관문을 그냥 통과해 계속 띄워지고,
     자식이 '중복'으로 즉시 종료되는 것을 감독기가 크래시로 오해하게 된다)"""
    if s.get("lock") and singleton.is_running(s["lock"]):
        return f"{s['lock']} 잠금을 다른 프로세스가 쥐고 있음"
    port = s.get("port")
    if _port_busy(port):
        if s.get("health") and _alive(s["health"]):
            return f"포트 {port} 에서 이미 정상 응답 중(다른 곳에서 띄운 것으로 보임)"
        return (f"포트 {port} 를 다른 프로세스가 물고 있으나 응답 없음 "
                f"(확인: netstat -ano | findstr :{port})")
    return ""


def status():
    print(f"AutoAd 상시 구동 점검  ({datetime.now().strftime('%H:%M:%S')})")

    sup = singleton.is_running("service")
    print(f"  · {'감독기(service.py)':38s} "
          f"{'실행 중 (pid ' + singleton.holder_pid('service') + ')' if sup else '멈춤'}")
    syn = singleton.is_running("cloud_sync")
    print(f"  · {'클라우드 수신함 동기화':38s} "
          f"{'실행 중 (pid ' + singleton.holder_pid('cloud_sync') + ')' if syn else '멈춤'}")

    for s in _services():
        if not s["health"]:
            continue          # sync 는 위에서 잠금으로 이미 판정했다
        ok = _alive(s["health"])
        print(f"  · {s['desc']:38s} {'실행 중' if ok else '멈춤'}")

    # 자동 시작 등록 여부(작업 스케줄러 또는 시작프로그램 폴더)
    print(f"\n  자동 시작 등록: "
          f"{'되어 있음' if startup_registered() else '안 되어 있음 (--install)'}")


def run_forever():
    # ── 단독 실행 보장 ────────────────────────────────────────
    # 두 벌이 뜨면 뒤에 뜬 쪽이 포트를 못 잡아 무한 재시작에 빠지고,
    # 동기화가 2개가 되어 같은 접수 리드를 두 번 등록할 수 있다.
    try:
        singleton.acquire("service")
    except singleton.AlreadyRunning as e:
        print(f"이미 구동 중입니다 (pid {e.pid}) — 이 실행은 종료합니다.")
        print("  상태 확인 :  python service.py --status")
        print("  정말 새로 띄우려면 기존 프로세스를 먼저 종료하세요.")
        return

    procs = {}        # name -> (Popen, logfile)
    fails = {}        # name -> 연속 실패 횟수
    halted = {}       # name -> 이 시각까지 재시도 안 함(0 이면 정상)
    foreign = {}      # name -> 마지막으로 알린 '남이 돌리는 중' 사유
    started = {}      # name -> 마지막 기동 시각(기동 유예 판단용)
    strikes = {}      # name -> 연속 헬스체크 실패 횟수
    stopping = {"v": False}

    def shutdown(*_):
        stopping["v"] = True
        _log("종료 요청 — 하위 프로세스 정리 중")
        for name, (p, fh) in procs.items():
            try:
                p.terminate()
            except Exception:
                pass
            try:
                fh.close()
            except Exception:
                pass
        _log("종료 완료")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    try:
        signal.signal(signal.SIGTERM, shutdown)
    except Exception:
        pass

    _log("=" * 56)
    _log("AutoAd 상시 구동 시작")
    if config.GLOBAL_DRY_RUN:
        _log("발행 모드: DRY-RUN (실제 게시 안 함)")
    else:
        _log("발행 모드: 실발행 ON — 승인된 건만 나갑니다")
    _log("=" * 56)

    while not stopping["v"]:
        for s in _services():
            name = s["name"]
            p = procs.get(name, (None, None))[0]
            if p is not None and p.poll() is None:
                continue                       # 정상 동작 중

            # 연속 실패로 손을 뗀 상태 — 영구가 아니라 쿨다운이다.
            # (영구 포기로 두면 sync 가 멈춘 채 접수 리드를 아무도 회수하지 않게 된다)
            if halted.get(name, 0) > time.time():
                continue
            if halted.get(name):
                _log(f"[{name}] 쿨다운 종료 — 다시 시도합니다.")
                halted[name] = 0
                fails[name] = 0

            # ⚠ '자식이 중복이라 비켰다(코드 3)'만 보고 continue 하면 영원히 안 뜬다.
            #   p.returncode 는 다시 띄우기 전까지 3 그대로이기 때문이다.
            #   그래서 판단은 항상 '지금도 남이 쓰고 있는가'(_occupied)로 한다.
            #   코드 3 은 '이번 종료를 실패로 세지 말라'는 뜻으로만 쓴다.
            stepped_aside = (p is not None and p.returncode == EXIT_ALREADY_RUNNING)

            # 이미 남이 돌리고 있으면 띄우지 않는다.
            # (예전엔 여기서 계속 기동을 시도해 154회 재시작 루프에 빠졌다)
            # 방금 죽은 자기 자식이 포트·잠금을 놓는 중일 수 있어 한 번 더 확인한다.
            reason = _occupied(s)
            if reason:
                time.sleep(2)
                reason = _occupied(s)
            if reason:
                if foreign.get(name) != reason:      # 사유가 바뀌면 다시 알린다
                    _log(f"[{name}] {reason} — 기동하지 않고 넘어갑니다.")
                    foreign[name] = reason
                # 남이 쓰는 동안은 실패로 세지 않는다(우리 잘못이 아니다).
                # 대신 다음 회차에 다시 확인해서, 비는 즉시 인수한다.
                continue
            if foreign.get(name):
                _log(f"[{name}] 보류 해제 — 기동합니다.")
            foreign[name] = ""

            if p is not None and not stepped_aside:   # 진짜로 죽은 경우만 실패로 센다
                fails[name] = fails.get(name, 0) + 1
                if fails[name] >= MAX_FAILS:
                    halted[name] = time.time() + HALT_COOLDOWN
                    _log(f"[{name}] 연속 {fails[name]}회 실패 — {HALT_COOLDOWN // 60}분 쉬었다가 "
                         f"다시 시도합니다. 그 전에 logs/{name}.log 를 확인하세요.")
                    continue
                wait = RESTART_BACKOFF[min(fails[name] - 1, len(RESTART_BACKOFF) - 1)]
                _log(f"[{name}] 종료됨(코드 {p.returncode}) — {wait}초 후 재시작 "
                     f"(연속 {fails[name]}/{MAX_FAILS}회) · 로그: logs/{name}.log")
                time.sleep(wait)
            else:
                fails.setdefault(name, 0)

            try:
                old_fh = procs.get(name, (None, None))[1]
                if old_fh is not None:
                    try:
                        old_fh.close()      # 재시작 때마다 핸들이 쌓이지 않도록
                    except Exception:
                        pass
                log_path = LOG_DIR / f"{name}.log"
                _rotate(log_path)
                fh = open(log_path, "a", encoding="utf-8", errors="replace")
                fh.write(f"\n===== {datetime.now().isoformat()} 시작 =====\n")
                fh.flush()
                np = subprocess.Popen(
                    s["cmd"], cwd=str(s["cwd"]), stdout=fh, stderr=subprocess.STDOUT,
                    env=CHILD_ENV,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                procs[name] = (np, fh)
                started[name] = time.time()
                strikes[name] = 0
                _log(f"[{name}] 기동 (pid {np.pid}) — {s['desc']}")
            except Exception as e:
                _log(f"[{name}] 기동 실패: {e}")

        time.sleep(20)

        # 헬스체크. 두 가지를 조심한다.
        #  · 기동 직후 느리게 뜨는 서버를 20초 한 번 보고 죽이면 안 된다 → STARTUP_GRACE
        #  · 순간적인 응답 끊김으로 멀쩡한 서버를 죽이면 안 된다 → 연속 HEALTH_STRIKES 회
        for s in _services():
            name = s["name"]
            if not s["health"]:
                continue
            p = procs.get(name, (None, None))[0]
            if p is None or p.poll() is not None:
                continue
            if time.time() - started.get(name, 0) < STARTUP_GRACE:
                continue                       # 아직 기동 중일 수 있다
            if _alive(s["health"]):
                strikes[name] = 0
                continue
            strikes[name] = strikes.get(name, 0) + 1
            if strikes[name] < HEALTH_STRIKES:
                _log(f"[{name}] 응답 없음 ({strikes[name]}/{HEALTH_STRIKES}) — 한 번 더 지켜봅니다")
                continue
            _log(f"[{name}] 연속 {strikes[name]}회 응답 없음 — 재시작")
            try:
                p.terminate()
            except Exception:
                pass

        # 성공적으로 살아있으면 실패 카운터 리셋
        for s in _services():
            name = s["name"]
            p = procs.get(name, (None, None))[0]
            if p is not None and p.poll() is None:
                if not s["health"] or _alive(s["health"]):
                    fails[name] = 0
        time.sleep(10)


def _startup_dir() -> Path:
    """현재 사용자의 시작프로그램 폴더. 여기에 넣으면 관리자 권한이 필요 없다."""
    base = os.environ.get("APPDATA", "")
    return Path(base) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


def _startup_file() -> Path:
    return _startup_dir() / f"{TASK_NAME}.vbs"


def _install_startup() -> bool:
    """시작프로그램 폴더에 등록(관리자 권한 불필요).

    .bat 를 넣으면 로그온 때마다 검은 창이 뜨므로, 창 없이 실행하는 .vbs 를 쓴다.
    한글 경로가 들어가므로 UTF-16 으로 저장한다(Windows Script Host 가 BOM 을 읽는다)."""
    runner = PYW if Path(PYW).exists() else PY
    target = _startup_file()
    vbs = (
        '\' AutoAd 상시 구동 — 로그온 시 자동 실행 (창 없이)\n'
        '\' 해제: 이 파일을 지우거나 python service.py --uninstall\n'
        'Set sh = CreateObject("WScript.Shell")\n'
        f'sh.CurrentDirectory = "{BASE}"\n'
        f'sh.Run """{runner}"" ""{BASE / "service.py"}""", 0, False\n'
    )
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(vbs, encoding="utf-16")
        return True
    except Exception as e:
        print(f"  시작프로그램 등록 실패: {e}")
        return False


def install():
    """로그온 시 자동 실행되도록 등록.
    작업 스케줄러를 먼저 시도하고, 권한이 없으면 시작프로그램 폴더로 대체한다."""
    runner = PYW if Path(PYW).exists() else PY
    cmd = f'"{runner}" "{BASE / "service.py"}"'
    r = subprocess.run(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", cmd,
         "/SC", "ONLOGON", "/RL", "LIMITED", "/F"],
        capture_output=True, text=True)
    if r.returncode == 0:
        print(f"등록 완료(작업 스케줄러) — 다음 로그온부터 자동 실행됩니다.")
        print(f"  작업 이름: {TASK_NAME}\n  실행: {cmd}")
        print("\n지금 바로 시작하려면:  schtasks /Run /TN AutoAd")
        return

    # 관리자 권한이 없으면 여기로 온다. 사용자 폴더는 권한 없이도 쓸 수 있다.
    print(f"작업 스케줄러 등록 불가({(r.stderr or r.stdout).strip()[:80]})")
    print("→ 시작프로그램 폴더로 등록합니다(관리자 권한 불필요)")
    if _install_startup():
        print(f"\n등록 완료 — 다음 로그온부터 자동 실행됩니다.")
        print(f"  파일: {_startup_file()}")
        print("  창 없이 실행되며, 해제는 python service.py --uninstall")
    else:
        print("\n두 방법 모두 실패했습니다. 관리자 권한 PowerShell 에서 다시 시도해 보세요.")


def startup_registered() -> bool:
    """자동 시작이 어느 방식으로든 등록돼 있는가."""
    try:
        if subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME],
                          capture_output=True, text=True).returncode == 0:
            return True
    except Exception:
        pass
    return _startup_file().exists()


def uninstall():
    done = []
    r = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
                       capture_output=True, text=True)
    if r.returncode == 0:
        done.append("작업 스케줄러")
    f = _startup_file()
    if f.exists():
        try:
            f.unlink()
            done.append("시작프로그램 폴더")
        except Exception as e:
            print(f"시작프로그램 파일 삭제 실패: {e}")
    print(f"등록 해제 완료 — {', '.join(done)}" if done else
          "해제할 등록이 없습니다.")


def once():
    """설치 검증용 — 각 서비스를 한 번 띄워보고 헬스체크 후 정리."""
    if singleton.is_running("service"):
        print(f"감독기가 이미 실행 중입니다 (pid {singleton.holder_pid('service')}).")
        print("  --once 는 포트를 뺏어 오지 못하므로 의미 있는 결과가 나오지 않습니다.")
        print("  현재 상태만 보려면:  python service.py --status")
        return False

    ok_all = True
    started = []
    for s in _services():
        # ⚠ sync 는 절대 여기서 띄우지 않는다.
        #   기동 즉시 클라우드 수신함을 pull 하는데, 클라우드는 가져가는 즉시 pulled 로
        #   마킹해 재수신이 안 된다. 12초 뒤 강제 종료하면 아직 등록 못 한 리드가
        #   영영 사라진다(실제 고객 이름·전화번호). 검증 때문에 리드를 잃을 수는 없다.
        if s["name"] == "sync":
            print(f"  건너뜀: {s['desc']} — 검증 중 접수 리드가 유실될 수 있어 제외")
            print(f"          (동기화만 따로 확인하려면: python cloud_sync.py)")
            continue
        occ = _occupied(s)
        if occ:
            print(f"  건너뜀: {s['desc']} — {occ}")
            ok_all = False
            continue
        fh = open(LOG_DIR / f"{s['name']}.log", "a", encoding="utf-8", errors="replace")
        p = subprocess.Popen(s["cmd"], cwd=str(s["cwd"]), stdout=fh,
                             stderr=subprocess.STDOUT, env=CHILD_ENV,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started.append((s, p, fh))
        print(f"  기동 시도: {s['desc']}")
    time.sleep(12)
    for s, p, fh in started:
        if s["health"]:
            ok = _alive(s["health"])
        else:
            ok = p.poll() is None
        print(f"  {'OK  ' if ok else '실패'} {s['desc']}" +
              ("" if ok else f"  → logs/{s['name']}.log 확인"))
        ok_all = ok_all and ok
    for s, p, fh in started:
        try:
            p.terminate()
        except Exception:
            pass
        try:
            fh.close()
        except Exception:
            pass
    print("\n" + ("전부 정상 기동 — --install 로 자동 시작 등록하세요."
                  if ok_all else "일부 실패 — data/logs/ 를 확인하세요."))
    return ok_all


def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--install", action="store_true")
    ap.add_argument("--uninstall", action="store_true")
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args()

    if a.status:
        status()
    elif a.install:
        install()
    elif a.uninstall:
        uninstall()
    elif a.once:
        once()
    else:
        run_forever()


if __name__ == "__main__":
    main()
