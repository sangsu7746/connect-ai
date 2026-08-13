"""
매일 한 건씩 자동 발행한다. 작업 스케줄러에 걸어 쓰는 것이 목적이다.

흐름:
  1. 발행할 상품 1건 고른다 (딥링크 있고, 아직 안 올린 것)
  2. **그 상품 가격을 다시 확인한다** — 며칠 지난 값을 '오늘 가격'처럼 올리면 안 된다
  3. 원고 생성 → 검사(가드레일 + 파트너스 표시 기준)
  4. 발행 → 공개 페이지에서 결과 검증
  5. 로그를 남긴다

의도적으로 하지 않는 것:
  - **하루 한 건을 넘기지 않는다.** 같은 블로그에 몰아 올리면 네이버가 스팸으로 본다.
  - **딥링크 없는 상품은 건드리지 않는다.** 수수료가 0원인 글을 쌓을 이유가 없다.
  - **연속 실패하면 멈춘다.** 같은 오류로 매일 브라우저를 띄우는 건 의미가 없다.
"""
import io
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime, timedelta

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.join(BASE_DIR, "price_history.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")
STATE = os.path.join(BASE_DIR, ".daily_state.json")
PY = os.path.join(BASE_DIR, ".venv", "Scripts", "python.exe")

MAX_PER_DAY = 10           # 하루 목표 발행 수(사용자 지정)
MAX_FAILS = 3              # 연속 실패가 이만큼이면 사람이 볼 때까지 멈춘다
PRICE_MAX_AGE_HOURS = 12   # 이보다 오래된 가격이면 다시 확인한다

#: 글과 글 사이 간격(초). 정확히 같은 간격으로 올리면 기계가 올린 티가 난다.
GAP_RANGE = (180, 480)
#: 한 번 실행에서 이 시간을 넘기면 남은 건은 다음 실행으로 넘긴다.
#: 실측상 1건에 21~33분이라 10건이면 4~6시간이다. PC 를 밤새 잡아두지 않기 위한 상한.
MAX_RUN_HOURS = 7


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(LOG_DIR, exist_ok=True)
    with io.open(os.path.join(LOG_DIR, f"publish-{datetime.now():%Y-%m}.log"),
                 "a", encoding="utf-8") as f:
        f.write(line + "\n")


def _state() -> dict:
    try:
        return json.load(io.open(STATE, encoding="utf-8"))
    except Exception:
        return {"fails": 0, "last_date": "", "count_today": 0}


def _save_state(s: dict) -> None:
    io.open(STATE, "w", encoding="utf-8").write(json.dumps(s, ensure_ascii=False, indent=2))


def pick_target() -> dict:
    """
    다음에 올릴 상품 하나. 조건은 셋 다 만족해야 한다.
      실측 데이터 / 파트너스 딥링크 보유 / 아직 이 채널에 안 올림
    할인율이 큰 것부터 고른다 — 읽는 사람에게 가치가 큰 순서다.
    """
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("""
            SELECT * FROM products p
             WHERE p.is_real = 1
               AND p.affiliate_url LIKE '%link.coupang.com%'
               AND p.current_price > 0
               AND p.product_id NOT IN (
                     SELECT product_id FROM published_posts WHERE channel = 'naver')
             ORDER BY p.discount_rate DESC, p.review_count DESC
             LIMIT 1
        """).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def refresh_price(product_id: str, detail_url: str = "") -> bool:
    """
    발행 직전에 가격을 다시 확인한다.

    며칠 전 값을 그대로 올리면 글에 적힌 가격이 실제와 다르다. 그건 거짓 정보이고,
    파트너스 기준과도 어긋난다. 수집은 브라우저를 띄우므로 실패할 수 있는데,
    실패하면 발행을 멈춘다 — 낡은 값으로 올리느니 하루 거르는 게 낫다.
    """
    target = detail_url or product_id
    log(f"  가격 재확인: {target[:60]}")
    try:
        r = subprocess.run(
            [PY, "-X", "utf8", "coupang_live_collector.py", "detail", target],
            cwd=BASE_DIR, capture_output=True, text=True, encoding="utf-8",
            errors="ignore", timeout=420)
    except subprocess.TimeoutExpired:
        log("  ✘ 가격 재확인 시간 초과")
        return False
    ok = r.returncode == 0 and "저장" in (r.stdout or "")
    if not ok:
        log(f"  ✘ 가격 재확인 실패: {(r.stdout or r.stderr or '')[-160:]}")
    return ok


def price_is_fresh(product: dict) -> bool:
    s = (product.get("updated_at") or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            t = datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt)
            return datetime.now() - t < timedelta(hours=PRICE_MAX_AGE_HOURS)
        except ValueError:
            continue
    return False


def remaining_stock() -> int:
    conn = sqlite3.connect(DB)
    try:
        return conn.execute("""
            SELECT COUNT(*) FROM products p WHERE p.is_real=1
              AND p.affiliate_url LIKE '%link.coupang.com%'
              AND p.product_id NOT IN (
                    SELECT product_id FROM published_posts WHERE channel='naver')
        """).fetchone()[0]
    finally:
        conn.close()


def publish_one(st: dict) -> str:
    """
    한 건 발행. 돌려주는 값: 'ok' | 'fail' | 'empty'
    한 건이 실패해도 그날 배치 전체를 접지 않는다 — 다음 상품으로 넘어간다.
    """
    target = pick_target()
    if not target:
        return "empty"

    pid = str(target["product_id"])
    log(f"대상: [{pid}] {target['title'][:44]}")

    if not price_is_fresh(target):
        if not refresh_price(pid, target.get("detail_url") or ""):
            log("  낡은 가격으로는 올리지 않습니다. 이 건은 건너뜁니다.")
            return "fail"
        target = pick_target() or target
        log(f"  갱신된 가격: {target['current_price']:,}원 "
            f"(할인 {target.get('discount_rate', 0)}%)")

    import coupang_blog_pipeline as P
    try:
        res = P.publish_to_naver(pid, logger_func=log)
    except Exception as e:
        log(f"  ✘ 발행 중 예외: {str(e)[:160]}")
        return "fail"

    if res.get("status") == "success":
        log(f"✅ 발행 완료: {res.get('title', '')[:50]}")
        log(f"   본문 {res.get('chars')}자 · 이미지 {res.get('images')}장 "
            f"· 카테고리 {res.get('category')}")
        return "ok"

    log(f"✘ 발행 실패({res.get('status')}): {res.get('why', '')[:140]}")
    return "fail"


def main() -> int:
    import random

    st = _state()
    today = datetime.now().strftime("%Y-%m-%d")
    if st.get("last_date") != today:
        st["last_date"], st["count_today"] = today, 0

    log("=" * 58)
    log(f"일일 자동 발행 시작 — 목표 {MAX_PER_DAY}건 (오늘 {st['count_today']}건 완료)")

    if st.get("fails", 0) >= MAX_FAILS:
        log(f"⛔ 연속 {st['fails']}회 실패로 멈춤 상태입니다.")
        log("   원인을 확인한 뒤 .daily_state.json 의 fails 를 0 으로 바꾸세요.")
        return 1

    stock = remaining_stock()
    log(f"발행 가능 재고: {stock}건")
    if stock < MAX_PER_DAY - st["count_today"]:
        log(f"⚠️ 재고({stock})가 오늘 목표보다 적습니다. 있는 만큼만 올립니다.")
        log("   딥링크 보충: python coupang_partners.py linkall 20")

    deadline = time.time() + MAX_RUN_HOURS * 3600
    done = 0
    while st["count_today"] < MAX_PER_DAY:
        if time.time() > deadline:
            log(f"⏱️ 실행 시간 상한({MAX_RUN_HOURS}시간)에 도달 — 나머지는 다음 실행으로 넘깁니다.")
            break

        n = st["count_today"] + 1
        log("-" * 58)
        log(f"[{n}/{MAX_PER_DAY}]")

        r = publish_one(st)
        if r == "empty":
            log("⛔ 더 올릴 상품이 없습니다 — 딥링크가 있는 미발행 상품이 0건입니다.")
            log("   쿠팡 파트너스에 로그인해 보충하세요: python coupang_partners.py linkall 20")
            break
        if r == "ok":
            st["fails"] = 0
            st["count_today"] += 1
            done += 1
        else:
            st["fails"] = st.get("fails", 0) + 1
            if st["fails"] >= MAX_FAILS:
                _save_state(st)
                log(f"⛔ 연속 {st['fails']}회 실패 — 오늘은 여기서 멈춥니다.")
                break
        _save_state(st)

        if st["count_today"] < MAX_PER_DAY:
            gap = random.randint(*GAP_RANGE)
            log(f"  다음 글까지 {gap // 60}분 {gap % 60}초 대기")
            time.sleep(gap)

    log("=" * 58)
    log(f"오늘 발행 {st['count_today']}건 (이번 실행 {done}건) · 남은 재고 {remaining_stock()}건")
    _save_state(st)
    return 0


if __name__ == "__main__":
    sys.exit(main())
