"""
이미 발행된 티스토리 글에 본문 이미지를 넣는다. 가능하면 대표이미지까지 잡는다.

왜 필요한가:
10건이 본문 이미지 0장으로 발행됐다. 업로드가 실패했는데 폴백이 없어서
자리표시자가 들어간 <p> 가 통째로 지워졌다(그 폴백은 이후 코드에 넣었지만,
이미 나간 글에는 적용되지 않는다).

이 스크립트가 하는 일 (로그인 1회):
  1. 업로드 경로를 실제로 확인한다.
     티스토리 편집기에는 input[type=file] 이 정적으로 없다("파일 입력 0개").
     사진 버튼이 파일 선택창을 띄우는 방식이라면 expect_file_chooser 로 잡아야 한다.
  2. 되면 티스토리에 올린 이미지를, 안 되면 쿠팡 CDN 주소를 본문에 끼워 넣는다.
     티스토리 업로드가 되어야 대표이미지(og:image)가 잡힌다 —
     쿠팡 주소는 본문에는 보이지만 대표이미지 후보가 되지 못한다.
"""
import json
import os
import re
import sqlite3
import sys
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
import tistory_poster as T
import coupang_blog_pipeline as P

HDR = {"User-Agent": "Mozilla/5.0 (compatible; KakaoTalk-Scrap/1.0)"}
LOG_PATH = os.path.join(BASE_DIR, "logs", "tistory-images.log")


def log(msg=""):
    """
    화면과 파일에 함께 남긴다.

    bat 으로 실행하면 출력이 사용자 콘솔로만 가서, 실패 원인을 나중에 확인할 수 없었다.
    (사진 버튼 후보 목록을 놓쳐서 업로드 실패 원인을 못 좁혔다)
    """
    print(msg)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"{msg}\n")
    except Exception:
        pass


def published_entries() -> list:
    """공개 RSS 로 글 번호와 제목을 얻는다. 관리 페이지를 긁는 것보다 안정적이다."""
    rss = urllib.request.urlopen(
        urllib.request.Request(f"https://{T.BLOG}.tistory.com/rss", headers=HDR),
        timeout=20).read().decode("utf-8", "ignore")
    items = re.findall(r"<item>(.*?)</item>", rss, re.S)
    out = []
    for it in items:
        link = re.search(r"<link>([^<]+)</link>", it)
        # `[^<\]]+` 로 잡으면 제목의 "[광고]" 닫는 괄호에서 잘려 '[광고' 만 남는다.
        title = re.search(r"<title>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", it, re.S)
        if not link:
            continue
        m = re.search(r"tistory\.com/(\d+)", link.group(1))
        if m:
            out.append({"id": int(m.group(1)),
                        "title": (title.group(1).strip() if title else "")})
    return out


def match_product(title: str) -> dict:
    """
    글 제목으로 DB 상품을 찾는다. 이미지 주소를 얻으려면 상품을 특정해야 한다.

    제목만으로는 안 맞는 경우가 있다 — 모델이 '스카치브라이트 철 수세미' 를
    '철수세미' 로 줄이거나 '백설 카놀라유 900ml 3개' 처럼 표기를 바꾼다.
    그래서 낱말 단위로 겹치는 정도를 보고 가장 잘 맞는 상품을 고른다.
    """
    t = re.sub(r"^\[광고\]\s*", "", title)
    words = [w for w in re.findall(r"[가-힣A-Za-z]{2,}", t) if len(w) >= 2][:6]
    if not words:
        return None
    conn = sqlite3.connect(os.path.join(BASE_DIR, "price_history.db"))
    conn.row_factory = sqlite3.Row
    try:
        # 티스토리에 올린 상품은 원장에 기록돼 있다. 제목 추측보다 이쪽이 정확하다
        # ('백설 카놀라유 900ml 3개' 가 '500ml 1개' 상품에 붙는 사고를 막는다).
        rows = conn.execute("""
            SELECT p.* FROM products p
            JOIN published_posts pp ON pp.product_id = p.product_id
            WHERE pp.channel='tistory' AND p.is_real=1
        """).fetchall()
        if not rows:
            rows = conn.execute("SELECT * FROM products WHERE is_real=1").fetchall()
    finally:
        conn.close()

    best, best_score = None, 0
    for r in rows:
        pt = r["title"] or ""
        # 상품명에서 공백을 지운 사본과도 대조한다('철 수세미' vs '철수세미')
        flat = pt.replace(" ", "")
        score = sum(1 for w in words if w in pt or w in flat)
        if score > best_score:
            best, best_score = r, score
    return dict(best) if best and best_score >= 2 else None


def coupang_image_urls(product: dict, n: int = 3) -> list:
    imgs = product.get("detail_images") or []
    if isinstance(imgs, str):
        try:
            imgs = json.loads(imgs)
        except Exception:
            imgs = []
    main = product.get("image_url")
    if main:
        imgs = [main] + [u for u in imgs if u != main]
    return [u for u in dict.fromkeys(imgs) if u and "/image/displayitem" not in u][:n]


def upload_via_chooser(page, paths: list, log=log) -> list:
    """
    사진 버튼을 눌러 뜨는 파일 선택창으로 업로드한다.

    input[type=file] 을 직접 찾는 방식은 실패했다 — 편집기에 그 요소가 없다.
    expect_file_chooser 는 숨은 input 과 네이티브 선택창을 모두 처리한다.
    """
    paths = [p for p in (paths or []) if p and os.path.exists(p)]
    if not paths:
        return []

    before = page.evaluate(T._EDITOR_IMGS_JS)
    seen = set(before.get("urls") or [])

    cands = page.evaluate("""() => {
        const vis = e => e.offsetParent !== null;
        return [...document.querySelectorAll('button, a, div[role=button], span[role=button]')]
          .filter(vis)
          .filter(b => /사진|이미지|photo|image/i.test(
              (b.getAttribute('aria-label')||'') + ' ' + (b.title||'') +
              ' ' + (b.className||'') + ' ' + (b.innerText||'')))
          .slice(0, 8)
          .map((b, i) => ({i, cls:(b.className||'').toString().slice(0,50),
                           label:(b.getAttribute('aria-label')||b.title||b.innerText||'').trim().slice(0,18)}));
    }""")
    log(f"    사진 버튼 후보 {len(cands)}개: " +
        ", ".join(f"{c['label'] or c['cls'][:18]}" for c in cands[:4]))
    if not cands:
        return []

    for c in cands[:4]:
        try:
            with page.expect_file_chooser(timeout=6000) as fc:
                page.evaluate("""(idx) => {
                    const vis = e => e.offsetParent !== null;
                    const list = [...document.querySelectorAll('button, a, div[role=button], span[role=button]')]
                      .filter(vis)
                      .filter(b => /사진|이미지|photo|image/i.test(
                          (b.getAttribute('aria-label')||'') + ' ' + (b.title||'') +
                          ' ' + (b.className||'') + ' ' + (b.innerText||'')));
                    if (list[idx]) list[idx].click();
                }""", c["i"])
            fc.value.set_files(paths)
            log(f"    ✔ 파일 선택창 잡음 (버튼 '{c['label'] or c['cls'][:16]}')")
            break
        except Exception:
            continue
    else:
        log("    ✘ 파일 선택창을 잡지 못했습니다")
        return []

    # 업로드가 끝나 본문에 주소가 꽂힐 때까지 기다린다
    for _ in range(20):
        page.wait_for_timeout(1500)
        cur = page.evaluate(T._EDITOR_IMGS_JS)
        got = [u for u in (cur.get("urls") or []) if u not in seen]
        if len(got) >= len(paths):
            return got
    cur = page.evaluate(T._EDITOR_IMGS_JS)
    return [u for u in (cur.get("urls") or []) if u not in seen]


def insert_images(html: str, urls: list) -> str:
    """
    본문 문단 사이에 이미지를 끼워 넣는다. 텍스트는 건드리지 않는다.
    build_html 과 같은 자리(둘째·넷째 문단 뒤)에 놓고, 남으면 뒤에 붙인다.
    """
    if not urls:
        return html
    tag = ('<p data-ke-size="size16">'
           '<img src="{}" style="max-width:100%;height:auto;" /></p>')
    parts = re.split(r"(?<=</p>)", html)
    parts = [x for x in parts if x.strip()]
    out, k = [], 0
    for i, seg in enumerate(parts):
        out.append(seg)
        # 0번은 대가성 고지다. 그 뒤 둘째·넷째 문단 뒤에 넣는다.
        if i in (2, 4) and k < len(urls):
            out.append(tag.format(urls[k]))
            k += 1
    while k < len(urls):
        out.append(tag.format(urls[k]))
        k += 1
    return "".join(out)


def main() -> int:
    limit = 10
    for a in sys.argv[1:]:
        if a.isdigit():
            limit = int(a)

    entries = [e for e in published_entries() if e["title"].startswith("[광고]")][:limit]
    log(f"대상 {len(entries)}건")
    for e in entries:
        log(f"  /{e['id']}  {e['title'][:46]}")

    jobs = []
    for e in entries:
        prod = match_product(e["title"])
        if not prod:
            log(f"  ? 상품 못 찾음: {e['title'][:40]}")
            continue
        paths = P.prepare_images(prod, 3, logger_func=lambda *a: None)
        jobs.append({"id": e["id"], "title": e["title"], "product": prod,
                     "paths": paths, "coupang": coupang_image_urls(prod, 3)})
    log(f"\n준비된 작업 {len(jobs)}건\n")
    if not jobs:
        return 1

    log("─" * 58)
    log("  브라우저가 열립니다. **티스토리(카카오)에 직접 로그인해 주세요.**")
    log("  로그인하시면 전부 자동으로 처리합니다.")
    log("─" * 58)

    ok = fallback = failed = 0
    with sync_playwright() as pw:
        ctx = T._ctx(pw, headless=False)
        p = T._page(ctx)
        p.on("dialog", lambda d: d.accept())
        try:
            if not T.ensure_login(p, wait_minutes=12):
                log("로그인 실패")
                return 1

            for i, j in enumerate(jobs, 1):
                log(f"\n[{i}/{len(jobs)}] /{j['id']} {j['title'][:42]}")
                try:
                    p.goto(T.EDIT_URL.format(id=j["id"]),
                           wait_until="domcontentloaded", timeout=45000)
                    p.wait_for_timeout(5000)
                    for txt in ("취소", "확인"):
                        try:
                            b = p.locator(f"button:has-text('{txt}')").first
                            if b.is_visible(timeout=900):
                                b.click(); p.wait_for_timeout(600); break
                        except Exception:
                            pass

                    cur = p.evaluate(T._READ_JS)
                    if not cur:
                        log("    ✘ 제목/본문을 읽지 못했습니다")
                        failed += 1
                        continue
                    if "<img" in cur["html"]:
                        log("    = 이미 이미지가 있습니다 — 건너뜁니다")
                        continue

                    urls = upload_via_chooser(p, j["paths"])
                    if urls:
                        log(f"    ✔ 티스토리 업로드 {len(urls)}장 (대표이미지 가능)")
                        ok += 1
                    else:
                        urls = j["coupang"]
                        log(f"    → 쿠팡 CDN {len(urls)}장으로 대체 (대표이미지는 안 잡힘)")
                        fallback += 1

                    new_html = insert_images(cur["html"], urls)
                    r = p.evaluate(T._FILL_JS, [cur["title"], new_html])
                    if not r.get("ok"):
                        log(f"    ✘ 본문 입력 실패: {r.get('why')}")
                        failed += 1
                        continue

                    p.locator("#publish-layer-btn").click()
                    p.wait_for_timeout(2000)
                    p.evaluate("""() => {
                        const inp = document.querySelector('#open20');
                        if (inp) (document.querySelector('label[for="open20"]') || inp).click();
                    }""")
                    p.wait_for_timeout(800)
                    p.locator("#publish-btn").click()
                    p.wait_for_timeout(6000)
                    log(f"    저장 {'완료' if '/manage/newpost' not in p.url else '확인 필요'}")
                except Exception as e:
                    log(f"    ✘ {str(e)[:100]}")
                    failed += 1
        finally:
            ctx.close()

    log("\n" + "=" * 58)
    log(f"티스토리 업로드 {ok}건 · 쿠팡 CDN 대체 {fallback}건 · 실패 {failed}건")
    return 0


if __name__ == "__main__":
    sys.exit(main())
