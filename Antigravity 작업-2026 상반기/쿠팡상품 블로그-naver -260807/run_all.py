"""
전체 자동 루프 — 딥링크 채우기 → 티스토리 발행 → 네이버 발행.

**순서에 이유가 있다.**
사람이 로그인해야 하는 단계를 앞으로 몰았다.
  1단계 딥링크   쿠팡 파트너스 로그인 필요   ~10분
  2단계 티스토리  카카오 로그인 필요         ~1시간
  3단계 네이버   무인(저장된 쿠키)          4~6시간
네이버를 먼저 돌리면 티스토리 로그인을 4시간 뒤에 요구하게 된다.
사람이 그때까지 기다릴 수 없으니, 손이 필요한 일을 먼저 끝내고
가장 오래 걸리는 무인 작업을 마지막에 둔다.

각 단계는 따로 실행되므로 하나가 실패해도 나머지는 계속 진행한다.
"""
import io
import os
import sqlite3
import subprocess
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PY = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")
if not os.path.exists(PY):
    PY = sys.executable
DB = os.path.join(BASE_DIR, "price_history.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")

TARGET_LINKS = 20      # 하루에 채울 딥링크
TARGET_NAVER = 10
TARGET_TISTORY = 10
#: 재고가 이만큼 있으면 딥링크 단계를 건너뛴다(쿠팡 접근을 아낀다)
LINK_STOCK_ENOUGH = 25


def log(msg=""):
    line = msg if not msg else f"[{datetime.now():%m-%d %H:%M:%S}] {msg}"
    print(line)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with io.open(os.path.join(LOG_DIR, f"runall-{datetime.now():%Y-%m}.log"),
                     "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def stock() -> dict:
    conn = sqlite3.connect(DB)
    try:
        q = lambda s: conn.execute(s).fetchone()[0]
        return {
            "links": q("SELECT COUNT(*) FROM products WHERE is_real=1 "
                       "AND affiliate_url LIKE '%link.coupang.com%'"),
            "naver": q("""SELECT COUNT(*) FROM products p WHERE p.is_real=1
                            AND p.affiliate_url LIKE '%link.coupang.com%'
                            AND p.product_id NOT IN (
                                SELECT product_id FROM published_posts WHERE channel='naver')"""),
            "tistory": q("""SELECT COUNT(*) FROM products p WHERE p.is_real=1
                            AND p.affiliate_url LIKE '%link.coupang.com%'
                            AND p.product_id NOT IN (
                                SELECT product_id FROM published_posts WHERE channel='tistory')"""),
        }
    finally:
        conn.close()


def run_stage(name: str, script: str, args: list, needs_login: str = "") -> bool:
    """한 단계를 따로 실행한다. 여기서 죽어도 다음 단계는 계속 간다."""
    log("")
    log("=" * 60)
    log(f"  {name}")
    if needs_login:
        log(f"  ** {needs_login} 로그인이 필요합니다. 창이 뜨면 로그인해 주세요. **")
    log("=" * 60)
    try:
        r = subprocess.run([PY, "-X", "utf8", "-u", script] + [str(a) for a in args],
                           cwd=BASE_DIR)
        ok = r.returncode == 0
        log(f"  {name} — {'완료' if ok else f'종료코드 {r.returncode}'}")
        return ok
    except Exception as e:
        log(f"  {name} — 실행 실패: {str(e)[:120]}")
        return False


def main() -> int:
    only = [a.lower() for a in sys.argv[1:] if not a.isdigit()]

    log("")
    log("#" * 60)
    log("  쿠팡 블로그 전체 자동 루프 시작")
    log("#" * 60)

    s = stock()
    log(f"재고 — 딥링크 {s['links']}건 · 네이버 대기 {s['naver']}건 · 티스토리 대기 {s['tistory']}건")
    log("")
    log("진행 순서 (사람이 로그인할 일을 앞에 둡니다):")
    log(f"  1. 딥링크 {TARGET_LINKS}건    — 쿠팡 파트너스 로그인 필요   약 10분")
    log(f"  2. 티스토리 {TARGET_TISTORY}건 — 카카오 로그인 필요          약 1시간")
    log(f"  3. 네이버 {TARGET_NAVER}건    — 무인(저장된 쿠키)          4~6시간")
    log("")
    log("  ※ PC 를 켜 둔 채로 두시고, 열리는 브라우저 창은 건드리지 마세요.")
    log("")

    # 시작 확인은 여기서 받는다.
    # .bat 에서 한글로 안내하면 CMD 가 UTF-8 을 명령으로 오독해 깨진다
    # ("'카카오' is not recognized" 오류가 실제로 났다). 파이썬은 UTF-8 이 정상이다.
    if sys.stdin and sys.stdin.isatty():
        try:
            if input("  시작하려면 Enter, 취소하려면 Ctrl+C > ") is None:
                return 1
        except (EOFError, KeyboardInterrupt):
            log("취소했습니다.")
            return 1

    done = {}

    # 1) 딥링크 — 재고가 넉넉하면 건너뛴다(쿠팡 접근을 아낀다)
    if not only or "links" in only:
        if s["links"] >= LINK_STOCK_ENOUGH:
            log("")
            log(f"1단계 건너뜀 — 딥링크 재고 {s['links']}건으로 충분합니다.")
            done["딥링크"] = "건너뜀"
        else:
            done["딥링크"] = ("완료" if run_stage(
                "1단계 · 딥링크 채우기", "daily_links.py", [TARGET_LINKS],
                needs_login="쿠팡 파트너스") else "실패")

    # 2) 티스토리 — 카카오 로그인이 필요하니 네이버보다 먼저 한다
    if not only or "tistory" in only:
        done["티스토리"] = ("완료" if run_stage(
            "2단계 · 티스토리 발행", "daily_tistory.py", [TARGET_TISTORY],
            needs_login="티스토리(카카오)") else "실패")

    # 3) 네이버 — 가장 오래 걸리고 사람 손이 필요 없다. 마지막에 둔다
    if not only or "naver" in only:
        done["네이버"] = ("완료" if run_stage(
            "3단계 · 네이버 발행", "daily_publish.py", []) else "실패")

    after = stock()
    log("")
    log("#" * 60)
    log("  전체 루프 종료")
    for k, v in done.items():
        log(f"    {k}: {v}")
    log(f"  재고 — 딥링크 {s['links']}→{after['links']} · "
        f"네이버 대기 {s['naver']}→{after['naver']} · "
        f"티스토리 대기 {s['tistory']}→{after['tistory']}")
    if after["naver"] < 5 or after["tistory"] < 5:
        log("  ⚠️ 발행 대기 재고가 적습니다. 다음 실행 전에 딥링크를 채우세요.")
    log("#" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
