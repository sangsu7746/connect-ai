"""
티스토리에 여러 건을 한 번에 발행한다.

왜 티스토리를 따로 챙기는가:
네이버는 robots.txt 에서 GPTBot·ClaudeBot·PerplexityBot 등을 전면 차단한다.
즉 네이버 글은 생성형 검색에 절대 인용되지 않는다. 티스토리는 본문을 전부 허용한다.
사람 유입은 네이버가, 생성형 검색 인용은 티스토리가 맡는 구조다.

**로그인은 사람이 한다.** 티스토리 세션 쿠키는 창을 닫으면 사라져서 실행마다 필요하다.
대신 한 번 로그인하면 그 세션에서 전부 처리한다.

발행 전에 네이버와 똑같은 검사를 통과해야 한다 —
가드레일(날조 차단) + 파트너스 표시 기준(제목 [광고]·고지 위치·확정 표현).
"""
import io
import os
import re
import sys
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

LOG_DIR = os.path.join(BASE_DIR, "logs")
TARGET_PER_RUN = 10


def log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%m-%d %H:%M:%S')}] {msg}"
    print(line)
    os.makedirs(LOG_DIR, exist_ok=True)
    with io.open(os.path.join(LOG_DIR, f"tistory-{datetime.now():%Y-%m}.log"),
                 "a", encoding="utf-8") as f:
        f.write(line + "\n")


def pick_targets(n: int) -> list:
    """
    티스토리에 아직 안 올린 상품을 고른다.
    네이버에 이미 올린 것도 대상이다 — 채널이 다르니 중복이 아니다.
    """
    import sqlite3
    import coupang_blog_pipeline as P
    conn = sqlite3.connect(os.path.join(BASE_DIR, "price_history.db"))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("""
            SELECT * FROM products p
             WHERE p.is_real = 1
               AND p.affiliate_url LIKE '%link.coupang.com%'
               AND p.current_price > 0
               AND p.product_id NOT IN (
                     SELECT product_id FROM published_posts WHERE channel = 'tistory')
             ORDER BY p.discount_rate DESC, p.review_count DESC
             LIMIT ?
        """, (n,)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def build_job(product: dict):
    """원고 생성 → 검사 → 발행용 job. 검사에 걸리면 None."""
    import coupang_blog_pipeline as P
    import tistory_poster as T
    import guardrails as G

    pid = str(product["product_id"])
    try:
        post = P.generate_post_draft(pid, logger_func=lambda *a: None)
    except Exception as e:
        log(f"  ✘ 원고 생성 실패: {str(e)[:80]}")
        return None

    if not post.get("guard", {}).get("ok", True):
        for b in post["guard"]["blocking"][:3]:
            log(f"  ⛔ {b}")
        return None

    title = P.ad_title(post["title"])
    aff = product.get("affiliate_url") or ""
    img_paths = P.prepare_images(product, 3, logger_func=lambda *a: None)
    html = T.build_html(post, product, aff, upload_slots=len(img_paths))

    # 파트너스 표시 기준을 실제 발행 HTML 로 확인한다
    probs = G.check_disclosure(re.sub(r"<[^>]+>", " ", html), title)
    if probs:
        for x in probs:
            log(f"  ⛔ {x}")
        return None

    try:
        tags = __import__("keyword_finder").keyword_string(product, n=10, log=lambda *a: None)
    except Exception:
        tags = re.split(r"[,(]", product.get("title", ""))[0].strip()

    return {
        "key": pid,
        "title": title,
        "html": html,
        "tags": tags,
        "category": T.to_tistory_category(P.map_blog_category(product)),
        "upload_paths": img_paths,
    }


def main() -> int:
    n = TARGET_PER_RUN
    for a in sys.argv[1:]:
        if a.isdigit():
            n = int(a)

    import coupang_blog_pipeline as P
    import tistory_poster as T

    log("=" * 58)
    log(f"티스토리 발행 시작 — 목표 {n}건")

    targets = pick_targets(n)
    if not targets:
        log("⛔ 올릴 상품이 없습니다 — 딥링크가 있는 티스토리 미발행 상품이 0건입니다.")
        log("   딥링크 보충: python daily_links.py")
        return 0
    log(f"대상 {len(targets)}건")

    # 원고는 브라우저 열기 전에 전부 만들어 둔다.
    # 로그인 대기 중에 원고를 만들면 세션이 놀고, 검사 실패분이 뒤늦게 드러난다.
    jobs = []
    for i, prod in enumerate(targets, 1):
        log(f"\n[{i}/{len(targets)}] 원고 준비: {prod['title'][:40]}")
        j = build_job(prod)
        if j:
            jobs.append(j)
            log(f"  ✔ {j['title'][:46]} · 태그 {len(j['tags'].split(','))}개 "
                f"· 이미지 {len(j['upload_paths'])}장 · 카테고리 '{j['category']}'")

    if not jobs:
        log("\n⛔ 검사를 통과한 원고가 없습니다.")
        return 1

    log("")
    log("─" * 58)
    log(f"  원고 {len(jobs)}건 준비 완료. 브라우저가 열립니다.")
    log("  **티스토리(카카오)에 직접 로그인해 주세요.** 비밀번호는 이 스크립트가 다루지 않습니다.")
    log("  로그인하시면 전부 자동으로 올립니다.")
    log("─" * 58)

    res = T.write_posts(jobs, mode="public", log=log)

    ok = 0
    for j in jobs:
        r = res.get(j["key"], {})
        if r.get("ok"):
            ok += 1
            P.record_published(j["key"], "tistory", r.get("url", ""))
            log(f"  ✅ {j['title'][:44]}")
        else:
            log(f"  ✘ {j['title'][:44]} — {r.get('why') or r.get('note')}")

    log("")
    log("=" * 58)
    log(f"티스토리 발행 {ok}/{len(jobs)}건")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
