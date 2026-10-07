"""
지금 바로 한 건 발행한다. 스케줄러를 기다리지 않는 수동 발행이다.

스케줄러(run_all.py)와 다른 점:
  · 상품과 채널을 사람이 고른다
  · 하루 상한을 넘겨도 올린다 — 사람이 직접 누른 것이므로 의도가 분명하다
    (다만 누적 수에는 반영한다. 스케줄러가 그만큼 덜 올리게 하려는 것이다)
  · 가격이 오래됐으면 확인 후 갱신한다

검사는 스케줄러와 똑같이 거친다 — 가드레일 + 파트너스 표시 기준.
급하게 올린다고 검사를 건너뛰면 그게 사고가 된다.
"""
import io
import json
import os
import re
import sqlite3
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DB = os.path.join(BASE_DIR, "price_history.db")


def candidates(channel: str, limit: int = 15) -> list:
    """딥링크가 있고 그 채널에 아직 안 올린 상품."""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT * FROM products p
             WHERE p.is_real = 1
               AND p.affiliate_url LIKE '%link.coupang.com%'
               AND p.current_price > 0
               AND p.product_id NOT IN (
                     SELECT product_id FROM published_posts WHERE channel = ?)
             ORDER BY p.discount_rate DESC, p.review_count DESC
             LIMIT ?
        """, (channel, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def ask(prompt: str, default: str = "") -> str:
    try:
        v = input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\n취소했습니다.")
        sys.exit(1)
    return v or default


def publish_naver(pid: str) -> bool:
    import coupang_blog_pipeline as P
    import daily_publish as D

    prod = next((x for x in __import__("coupang_collector").get_all_products_from_db()
                 if str(x["product_id"]) == pid), None)
    if prod and not D.price_is_fresh(prod):
        print("  가격이 오래됐습니다. 다시 확인합니다...")
        if not D.refresh_price(pid, prod.get("detail_url") or ""):
            print("  ✘ 가격 확인 실패 — 낡은 값으로는 올리지 않습니다.")
            return False

    P.clear_published(pid, "naver")          # 수동 발행은 중복 가드를 넘어간다
    r = P.publish_to_naver(pid)
    ok = r.get("status") == "success"
    print(f"  {'✅' if ok else '✘'} 네이버: {r.get('title') or r.get('why', '')}")
    return ok


def publish_tistory(pid: str) -> bool:
    import coupang_blog_pipeline as P
    import tistory_poster as T
    import daily_tistory as DT
    import coupang_collector as C

    prod = next((x for x in C.get_all_products_from_db()
                 if str(x["product_id"]) == pid), None)
    if not prod:
        print("  ✘ DB 에 상품이 없습니다.")
        return False

    job = DT.build_job(prod)
    if not job:
        print("  ✘ 원고가 검사를 통과하지 못했습니다.")
        return False

    P.clear_published(pid, "tistory")
    res = T.write_posts([job], mode="public")
    r = res.get(job["key"], {})
    ok = bool(r.get("ok"))
    if ok:
        P.record_published(pid, "tistory", r.get("url", ""))
    print(f"  {'✅' if ok else '✘'} 티스토리: {job['title'] if ok else (r.get('why') or '')}")
    return ok


def main() -> int:
    print("=" * 62)
    print("  실시간 발행 — 지금 바로 한 건 올립니다")
    print("=" * 62)

    ch = ask("\n  채널 (1=네이버  2=티스토리  3=둘 다) [1] > ", "1")
    channels = {"1": ["naver"], "2": ["tistory"], "3": ["naver", "tistory"]}.get(ch)
    if not channels:
        print("  1, 2, 3 중에서 골라 주세요.")
        return 1

    # 두 채널이면 양쪽 다 미발행인 상품을 보여준다
    cands = candidates(channels[0])
    if len(channels) > 1:
        other = {str(x["product_id"]) for x in candidates(channels[1], 100)}
        cands = [c for c in cands if str(c["product_id"]) in other] or cands

    if not cands:
        print("\n  ⛔ 올릴 상품이 없습니다 — 딥링크가 있는 미발행 상품이 0건입니다.")
        print("     python daily_links.py 로 딥링크를 채우세요.")
        return 1

    print(f"\n  발행 대기 (할인율 높은 순)")
    for i, c in enumerate(cands[:10], 1):
        print(f"    {i:>2}. {c['title'][:40]:42s} {c['current_price']:>7,}원 "
              f"({c.get('discount_rate', 0)}%)")

    sel = ask(f"\n  번호 [1] > ", "1")
    if not sel.isdigit() or not (1 <= int(sel) <= len(cands[:10])):
        print("  목록에 있는 번호를 골라 주세요.")
        return 1
    target = cands[int(sel) - 1]
    pid = str(target["product_id"])

    print()
    print("─" * 62)
    print(f"  {target['title'][:46]}")
    print(f"  {target['current_price']:,}원 · 채널 {', '.join(channels)}")
    print("─" * 62)
    if ask("  이대로 발행할까요? (Enter=발행, n=취소) > ").lower() == "n":
        print("  취소했습니다.")
        return 1

    ok_count = 0
    for c in channels:
        print(f"\n[{c}] 발행 중...")
        try:
            ok = publish_naver(pid) if c == "naver" else publish_tistory(pid)
        except Exception as e:
            print(f"  ✘ 오류: {str(e)[:140]}")
            ok = False
        ok_count += 1 if ok else 0

    # 스케줄러가 그만큼 덜 올리도록 누적에 반영한다
    if ok_count:
        _bump_counters(channels)

    print()
    print("=" * 62)
    print(f"  발행 {ok_count}/{len(channels)}건 완료")
    return 0 if ok_count else 1


def _bump_counters(channels: list) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    for path, ch in ((".daily_state.json", "naver"), (".tistory_state.json", "tistory")):
        if ch not in channels:
            continue
        p = os.path.join(BASE_DIR, path)
        try:
            s = json.load(io.open(p, encoding="utf-8"))
        except Exception:
            s = {"last_date": "", "count_today": 0}
        if s.get("last_date") != today:
            s["last_date"], s["count_today"] = today, 0
        s["count_today"] = s.get("count_today", 0) + 1
        io.open(p, "w", encoding="utf-8").write(json.dumps(s, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    code = main()
    print()
    try:
        input("  창을 닫으려면 Enter > ")
    except Exception:
        pass
    sys.exit(code)
