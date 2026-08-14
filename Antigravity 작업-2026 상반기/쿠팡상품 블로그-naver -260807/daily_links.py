"""
매일 딥링크를 채운다. 작업 스케줄러에 걸어 쓰는 것이 목적이다.

**이 작업만은 완전 자동이 아니다.** 쿠팡 파트너스가 로그인을 요구하고,
이 스크립트는 아이디·비밀번호를 다루지 않는다. 창이 열리면 사람이 직접 로그인해야 한다.
대신 로그인은 하루 한 번뿐이고, 그 세션에서 20건을 연달아 만든다.
(쿠팡 인증 쿠키는 전부 세션 쿠키라 창을 닫으면 사라진다 — 그래서 한 세션에 몰아 처리한다)

발행보다 먼저 돌려야 한다. 딥링크가 없으면 발행해도 수수료가 0원이다.
"""
import io
import json
import os
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.join(BASE_DIR, "price_history.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")

TARGET_PER_DAY = 20        # 하루에 채울 딥링크 수
LOGIN_WAIT_MIN = 12.0      # 사람이 로그인할 때까지 기다리는 시간


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(LOG_DIR, exist_ok=True)
    with io.open(os.path.join(LOG_DIR, f"links-{datetime.now():%Y-%m}.log"),
                 "a", encoding="utf-8") as f:
        f.write(line + "\n")


def stock() -> dict:
    """현재 딥링크 재고. 발행 가능한 것과 전체를 나눠서 본다."""
    conn = sqlite3.connect(DB)
    try:
        have = conn.execute(
            "SELECT COUNT(*) FROM products WHERE is_real=1 "
            "AND affiliate_url LIKE '%link.coupang.com%'").fetchone()[0]
        ready = conn.execute("""
            SELECT COUNT(*) FROM products p WHERE p.is_real=1
              AND p.affiliate_url LIKE '%link.coupang.com%'
              AND p.product_id NOT IN (
                    SELECT product_id FROM published_posts WHERE channel='naver')
        """).fetchone()[0]
        need = conn.execute("""
            SELECT COUNT(*) FROM products WHERE is_real=1 AND detail_url<>''
              AND (affiliate_url IS NULL OR affiliate_url NOT LIKE '%link.coupang.com%')
        """).fetchone()[0]
    finally:
        conn.close()
    return {"have": have, "ready": ready, "need": need}


def main() -> int:
    n = TARGET_PER_DAY
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)

    log("=" * 58)
    s = stock()
    log(f"딥링크 채우기 시작 — 목표 {n}건")
    log(f"  현재 보유 {s['have']}건 · 발행 대기 {s['ready']}건 · 미보유 {s['need']}건")

    if s["need"] == 0:
        log("모든 실측 상품에 딥링크가 있습니다. 할 일이 없습니다.")
        log("  새 상품이 필요하면 먼저 수집하세요:")
        log("  python coupang_live_collector.py list 60")
        return 0

    n = min(n, s["need"])
    log("")
    log("─" * 58)
    log("  브라우저가 열립니다. **쿠팡 파트너스에 직접 로그인해 주세요.**")
    log("  비밀번호는 이 스크립트가 다루지 않습니다.")
    log(f"  로그인하시면 {n}건을 자동으로 만듭니다. (최대 {LOGIN_WAIT_MIN:.0f}분 대기)")
    log("─" * 58)
    log("")

    import coupang_partners as CP
    try:
        made = CP.link_batch(limit=n, wait_minutes=LOGIN_WAIT_MIN)
    except Exception as e:
        log(f"✘ 실행 중 예외: {str(e)[:160]}")
        return 1

    after = stock()
    log("")
    log("=" * 58)
    log(f"생성 {made}/{n}건 · 보유 {s['have']} → {after['have']}건 "
        f"· 발행 대기 {after['ready']}건")

    if after["ready"] < 10:
        log(f"⚠️ 발행 대기가 {after['ready']}건입니다. 하루 10건 목표에는 모자랍니다.")
    if made == 0:
        log("⚠️ 한 건도 만들지 못했습니다. 로그인이 안 됐거나 상품 매칭에 실패했습니다.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
