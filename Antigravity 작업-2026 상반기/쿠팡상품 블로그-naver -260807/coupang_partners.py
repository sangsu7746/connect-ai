"""
coupang_partners.py
쿠팡 파트너스에서 상품 딥링크(단축 URL)를 만들어 DB 에 저장한다.

왜 필요한가:
  수집기가 저장하는 affiliate_url 은 그냥 상품 페이지 주소라 추적 코드가 없다.
  그대로 글을 올리면 방문자가 사도 쿠팡이 누가 보냈는지 몰라 수수료가 0원이다.
  https://link.coupang.com/a/XXXX 형태여야 수익이 발생한다.

로그인 원칙:
  아이디·비밀번호를 코드가 다루지 않는다. 최초 1회 사람이 직접 로그인하고,
  그 세션을 전용 프로필(.partners_profile)에 남겨 이후 재사용한다.
  (tistory_poster.py 와 같은 방식)

사용법:
  python coupang_partners.py login              # 최초 로그인 (사람이 직접)
  python coupang_partners.py status             # 세션 상태만 확인
  python coupang_partners.py inspect            # 링크생성 화면 구조 덤프(개발용)
  python coupang_partners.py link <상품ID>       # 한 건 딥링크 생성 후 DB 저장
  python coupang_partners.py linkall [개수]      # 딥링크 없는 상품들을 순차 처리
"""
import os
import re
import sys
import time
import json
import sqlite3

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "price_history.db")
PROFILE_DIR = os.path.join(BASE_DIR, ".partners_profile")

PARTNERS_HOME = "https://partners.coupang.com"
LINK_PAGE = "https://partners.coupang.com/#affiliate/ws/link"

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]


def _ctx(pw, headless=False):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    return pw.chromium.launch_persistent_context(
        PROFILE_DIR, headless=headless, args=LAUNCH_ARGS,
        locale="ko-KR", timezone_id="Asia/Seoul", no_viewport=True,
    )


def _page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _logged_in(page) -> bool:
    """
    '로그인 페이지가 아니다'가 아니라 '파트너스 화면에 들어와 있다'로 판정한다.
    (티스토리에서 URL 부재만 보고 판정했다가 비밀번호 창을 통과로 오판한 적이 있다)
    """
    # 키워드로 맞히려다 오늘만 네 번 틀렸다(티스토리·네이버·파트너스).
    # 화면 문구는 개편으로 바뀌지만 '로그인 폼의 존재'는 안 바뀐다.
    #   · partners 도메인에 있고
    #   · 로그인 입력창이 없으면
    # 로그인된 것으로 본다. 부정 조건이 아니라 구조로 가르는 방식이다.
    try:
        u = (page.url or "").lower()
        if "partners.coupang.com" not in u:
            return False
        return bool(page.evaluate("""() => {
            const form = document.querySelector(
                '#login-email-input, #login-password-input, input[type="password"]');
            return !form;
        }"""))
    except Exception:
        return False


def _on_link_page(page) -> bool:
    """링크 생성 화면에 '실제로' 들어와 검색창까지 떴는지 확인한다."""
    try:
        page.goto(LINK_PAGE, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector("input[placeholder*='검색']", timeout=25000)
        return True
    except Exception:
        return False


def ensure_login(page, wait_minutes: float = 6.0) -> bool:
    """
    파트너스 링크 생성 화면까지 들어간다. 로그인 화면이면 사람을 기다린다.

    루트(partners.coupang.com)는 로그인 없이도 잠깐 열려서, 거기서 판정하면
    통과로 오인한다. 실제로 쓸 화면(링크 생성)에서 검색창이 뜨는지로 판정해야 한다.
    """
    if _on_link_page(page):
        return True
    page.goto(PARTNERS_HOME, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    if _logged_in(page) and _on_link_page(page):
        return True

    print("\n" + "=" * 62)
    print("  쿠팡 파트너스 로그인이 필요합니다.")
    print("  ** 지금 열린 창에서 ** 직접 로그인해 주세요.")
    print("  비밀번호는 이 스크립트가 다루지 않습니다.")
    print(f"  최대 {wait_minutes:.0f}분 기다립니다...")
    print("=" * 62 + "\n")

    deadline = time.time() + wait_minutes * 60
    last = ""
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        host = re.sub(r"^https?://([^/]+).*$", r"\1", page.url or "")
        if host != last:
            print(f"    현재 위치: {host}")
            last = host
        if _logged_in(page) and _on_link_page(page):
            print("  로그인 확인됨 (링크 생성 화면 도달).")
            return True
    print("  시간 초과 — 로그인되지 않았습니다.")
    return False


INSPECT_JS = r"""() => {
  const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
  const brief = e => ({tag:e.tagName, id:e.id||'', type:e.type||'',
                       cls:(e.className||'').toString().slice(0,46),
                       ph:e.getAttribute('placeholder')||'',
                       txt:(e.innerText||e.value||'').trim().slice(0,24)});
  return {
    url: location.href,
    title: document.title,
    inputs: [...document.querySelectorAll('input:not([type=hidden]), textarea')]
              .filter(vis).slice(0,14).map(brief),
    buttons: [...document.querySelectorAll('button, a[role=button]')]
              .filter(vis).slice(0,20).map(brief),
    menus: [...document.querySelectorAll('a')].filter(vis)
              .map(a => (a.innerText||'').trim()).filter(t => t && t.length <= 14).slice(0,24),
    bodyHead: (document.body ? document.body.innerText : '').slice(0, 300).replace(/\n+/g,' | ')
  };
}"""


def inspect_ui():
    """링크 생성 화면 구조를 덤프한다. 셀렉터를 추측하지 않기 위한 개발용."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _ctx(pw)
        p = _page(ctx)
        try:
            if not ensure_login(p, wait_minutes=8):
                return None
            p.goto(LINK_PAGE, wait_until="domcontentloaded", timeout=45000)
            p.wait_for_timeout(5000)
            # 링크 페이지로 갔다가 로그인으로 튕기는 경우가 있다 — 여기서 다시 확인한다
            if not _logged_in(p):
                print("  링크 페이지에서 로그인으로 튕겼습니다. 다시 로그인해 주세요.")
                if not ensure_login(p, wait_minutes=6):
                    return None
                p.goto(LINK_PAGE, wait_until="domcontentloaded", timeout=45000)
                p.wait_for_timeout(5000)
            info = p.evaluate(INSPECT_JS)
            print(f"URL   : {info['url'][:70]}")
            print(f"TITLE : {info['title'][:40]}")
            print(f"\n[본문] {info['bodyHead'][:240]}")
            for key in ("inputs", "buttons"):
                print(f"\n[{key}]")
                for e in info[key]:
                    print("   ", {k: v for k, v in e.items() if v})
            print(f"\n[메뉴] {', '.join(info['menus'])}")
            return info
        finally:
            ctx.close()


_SHORT_RE = re.compile(r"https://link\.coupang\.com/\S+")


def _search_query(title: str) -> str:
    """
    상품명을 검색어로 다듬는다.
    옵션 꼬리표(', 1L, 12개')와 대괄호 태그는 빼야 검색이 잘 걸린다.
    """
    t = re.sub(r"\[[^\]]*\]", " ", title or "")      # [주방용품] 같은 태그 제거
    t = t.split(",")[0]                               # 첫 콤마 앞까지가 상품명
    t = re.sub(r"\s+", " ", t).strip()
    return t[:30]


def _dump_state(page, tag: str) -> None:
    """무슨 화면인지 눈으로 확인하기 위한 덤프. 셀렉터를 추측하지 않으려는 장치."""
    try:
        r = page.evaluate(r"""() => {
          const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
          return {
            shorts: (document.body.innerText.match(/https:\/\/link\.coupang\.com\/\S+/g)||[]).slice(0,3),
            btns: [...document.querySelectorAll('button, a')].filter(vis)
              .map(e => ({cls:(e.className||'').toString().slice(0,38),
                          txt:(e.innerText||'').trim().replace(/\n+/g,'/').slice(0,20)}))
              .filter(o => o.txt).slice(0,20),
            inputs: [...document.querySelectorAll('input, textarea')].filter(vis)
              .map(e => ({cls:(e.className||'').toString().slice(0,34),
                          ph:e.getAttribute('placeholder')||'',
                          val:(e.value||'').slice(0,40)})).slice(0,8),
            body: document.body.innerText.slice(0,300).replace(/\n+/g,' | ')
          };
        }""")
        print(f"\n  ── [{tag}] ──")
        print("   본문:", r["body"][:220])
        if r["shorts"]:
            print("   단축URL:", r["shorts"])
        print("   입력창:", [x for x in r["inputs"] if x.get("ph") or x.get("val")][:4])
        print("   버튼:", [b["txt"] for b in r["btns"]][:14])
    except Exception as e:
        print(f"  덤프 실패({tag}): {str(e)[:50]}")


def _type_query(page, box, text: str, verbose: bool = False) -> bool:
    """
    검색어를 넣고 '실제로 들어갔는지' 확인한다.

    fill() 로 URL 을 넣었더니 'https:' 까지만 들어가 검색이 헛돌았다
    (Ant Design 입력창이 값을 가로챈 것으로 보인다). 한 글자씩 입력하고 검증한다.
    """
    for attempt in range(3):
        try:
            box.click()
            page.keyboard.press("Control+A")
            page.keyboard.press("Delete")
            page.wait_for_timeout(250)
            box.type(text, delay=25)
            page.wait_for_timeout(500)
            got = (box.input_value() or "").strip()
            if got == text.strip():
                return True
            if verbose:
                print(f"    입력 불일치({attempt + 1}차): '{got[:40]}'")
            # JS 로 직접 넣고 이벤트를 발생시킨다
            page.evaluate("""([el, v]) => {
                const setter = Object.getOwnPropertyDescriptor(
                    window.HTMLInputElement.prototype, 'value').set;
                setter.call(el, v);
                el.dispatchEvent(new Event('input', {bubbles: true}));
                el.dispatchEvent(new Event('change', {bubbles: true}));
            }""", [box.element_handle(), text])
            page.wait_for_timeout(500)
            if (box.input_value() or "").strip() == text.strip():
                return True
        except Exception as e:
            if verbose:
                print(f"    입력 오류({attempt + 1}차): {str(e)[:50]}")
    return False


def make_deeplink(page, product_url: str, verbose: bool = False,
                  fallback_title: str = "", current_price: int = 0) -> str:
    """
    상품 URL 하나를 파트너스에 넣어 단축 URL 을 받아온다.
    실패하면 빈 문자열을 돌려준다(예외를 올리지 않는다).
    """
    try:
        page.goto(LINK_PAGE, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_selector("input[placeholder*='검색']", timeout=30000)
        page.wait_for_timeout(1200)

        # 이 검색창은 URL 을 받지 않는다. 넣어도 'https:' 까지만 남고 잘린다(실측).
        # 상품명으로 검색한 뒤, 결과 중에서 해당 상품을 골라야 한다.
        box = page.locator("input[placeholder*='검색']").first
        query = _search_query(fallback_title or product_url)
        if not _type_query(page, box, query, verbose):
            print(f"    검색어를 입력하지 못했습니다: {query[:40]}")
            return ""
        if verbose:
            print(f"    검색어: {query}")

        page.keyboard.press("Enter")
        page.wait_for_timeout(6000)

        if verbose:
            res = page.evaluate(r"""() => {
              const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
              // 상품 카드로 보이는 것들 (이미지+텍스트를 함께 가진 블록)
              const cards = [...document.querySelectorAll('div, li, article')]
                .filter(e => vis(e) && e.querySelector('img') &&
                             (e.innerText||'').trim().length > 10 &&
                             (e.innerText||'').trim().length < 200)
                .slice(0, 6)
                .map(e => ({cls:(e.className||'').toString().slice(0,40),
                            txt:(e.innerText||'').trim().replace(/\n+/g,' | ').slice(0,70),
                            btns:[...e.querySelectorAll('button, a')].filter(vis)
                                  .map(b=>(b.innerText||'').trim().slice(0,14)).filter(Boolean)}));
              // 모든 '링크' 관련 클릭 요소를 위치와 함께
              const links = [...document.querySelectorAll('button, a')].filter(vis)
                .filter(e => /링크|생성|복사/.test(e.innerText||''))
                .map(e => ({tag:e.tagName, txt:(e.innerText||'').trim().slice(0,16),
                            cls:(e.className||'').toString().slice(0,34),
                            top: Math.round(e.getBoundingClientRect().top),
                            inNav: !!e.closest('nav, [class*="menu"], [class*="sider"], [class*="Sider"]')}));
              return {cards, links, imgs: document.querySelectorAll('img').length};
            }""")
            print(f"\n  ── [검색 결과] 이미지 {res['imgs']}개 ──")
            for c in res["cards"]:
                print(f"   카드 .{c['cls']}: {c['txt'][:64]}")
                if c["btns"]:
                    print(f"        버튼 {c['btns']}")
            print("   링크 관련 요소:")
            for l in res["links"]:
                print("     ", {k: v for k, v in l.items() if v not in ("", False)})

        # 이미 화면에 단축 URL 이 보이면 그대로 쓴다
        found = _SHORT_RE.findall(page.evaluate("() => document.body.innerText"))
        if found:
            return found[0].rstrip(".,)")

        # 결과 구조(실측): .product-row > div.product-item 여러 개.
        # 각 product-item 안에 '상품정보' / '링크 생성' 버튼이 있는데
        # hover 전에는 숨어 있어 가시성 필터로 찾으면 하나도 안 잡힌다.
        # 그래서 '보이는가'가 아니라 '어느 상품 안에 있는가'로 고른다.
        #
        # 같은 브랜드의 다른 옵션(1L 6개 vs 1L 12개)이 함께 나오므로
        # 제목 조각과 현재가를 함께 대조해야 엉뚱한 상품 링크를 만들지 않는다.
        clicked = page.evaluate(r"""([titleKey, priceStr]) => {
          const items = [...document.querySelectorAll('.product-item')];
          if (!items.length) return {err: 'product-item 없음'};

          const norm = s => (s || '').replace(/\s+/g, ' ').trim();
          const scored = items.map(it => {
            const t = norm(it.innerText);
            let score = 0;
            if (priceStr && t.includes(priceStr)) score += 3;   // 가격 일치가 가장 확실
            const words = titleKey.split(' ').filter(w => w.length > 1);
            words.forEach(w => { if (t.includes(w)) score += 1; });
            return {it, t, score};
          }).sort((a, b) => b.score - a.score);

          const best = scored[0];
          if (!best || best.score < 2) return {err: '일치 상품 없음',
                                               cands: scored.slice(0,3).map(s=>s.t.slice(0,50))};
          const btn = [...best.it.querySelectorAll('button, a')]
            .find(b => /링크\s*생성|링크\s*만들기/.test(b.innerText || ''));
          if (!btn) return {err: '링크 버튼 없음', matched: best.t.slice(0,50)};
          btn.click();
          return {ok: true, matched: best.t.slice(0, 56), score: best.score};
        }""", [_search_query(fallback_title or ""),
               f"{current_price:,}원" if current_price else ""])

        if verbose:
            print("   상품 매칭:", clicked)
        if not clicked or clicked.get("err"):
            print(f"    상품을 특정하지 못했습니다: {(clicked or {}).get('err')}")
            return ""
        page.wait_for_timeout(4500)
        if verbose:
            _dump_state(page, "링크생성 클릭 후")

        found = _SHORT_RE.findall(page.evaluate("() => document.body.innerText"))
        if found:
            return found[0].rstrip(".,)")

        # 입력창(생성 결과가 input 에 담기는 경우)도 훑는다
        vals = page.evaluate("""() => [...document.querySelectorAll('input, textarea')]
            .map(e => e.value || '').filter(v => v.includes('link.coupang.com'))""")
        if vals:
            m = _SHORT_RE.search(vals[0])
            if m:
                return m.group(0)
        return ""
    except Exception as e:
        print(f"    링크 생성 오류: {str(e)[:70]}")
        return ""


def link_batch(limit: int = 5, wait_minutes: float = 10.0, headless: bool = False) -> int:
    """
    한 번 로그인한 세션에서 여러 건을 연속 처리한다.

    쿠팡 로그인 인증 쿠키(authLoginSessionId 등)는 전부 세션 쿠키라
    브라우저를 닫으면 사라진다. 그래서 프로필을 남겨도 재로그인이 필요하다.
    대신 창을 닫지 않고 한 세션 안에서 여러 건을 처리하면 로그인은 1회로 끝난다.
    """
    from playwright.sync_api import sync_playwright
    import random

    targets = pending_links(limit)
    if not targets:
        print("딥링크가 필요한 상품이 없습니다.")
        return 0
    print(f"대상 {len(targets)}건 — 로그인 후 순차 처리합니다.\n")

    done = 0
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless)
        p = _page(ctx)
        try:
            if not ensure_login(p, wait_minutes=wait_minutes):
                print("로그인 실패 — 중단합니다.")
                return 0
            print("로그인 완료. 링크 생성을 시작합니다.\n")

            for i, t in enumerate(targets, 1):
                print(f"[{i}/{len(targets)}] {t['title'][:34]}")
                link = make_deeplink(p, t["detail_url"], verbose=(i == 1),
                                     fallback_title=t["title"],
                                     current_price=t.get("current_price") or 0)
                if link:
                    save_link(t["product_id"], link)
                    print(f"    ✅ {link}")
                    done += 1
                else:
                    print("    ✘ 링크를 얻지 못했습니다")
                if i < len(targets):
                    p.wait_for_timeout(int(random.uniform(4, 8) * 1000))
        finally:
            ctx.close()
    print(f"\n완료: {done}/{len(targets)}건")
    return done


def session_status() -> dict:
    """브라우저를 띄우지 않고 프로필 존재 여부만 본다."""
    ck = os.path.join(PROFILE_DIR, "Default", "Network", "Cookies")
    if not os.path.exists(ck):
        ck = os.path.join(PROFILE_DIR, "Default", "Cookies")
    if not os.path.exists(ck):
        return {"ok": False, "why": "프로필 없음 — 최초 로그인이 필요합니다"}
    return {"ok": True, "why": f"프로필 있음 ({os.path.getsize(ck) // 1024}KB)"}


def pending_links(limit: int = 20) -> list:
    """딥링크가 아직 없는 실측 상품을 고른다."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT product_id, title, detail_url, affiliate_url, current_price
        FROM products
        WHERE is_real=1 AND detail_url<>''
          AND (affiliate_url IS NULL OR affiliate_url NOT LIKE '%link.coupang.com%')
        ORDER BY discount_rate DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_link(product_id: str, deeplink: str) -> bool:
    """생성한 딥링크를 DB 에 저장한다."""
    if "link.coupang.com" not in (deeplink or ""):
        raise ValueError(f"파트너스 딥링크가 아닙니다: {deeplink[:60]}")
    conn = sqlite3.connect(DB_PATH)
    n = conn.execute("UPDATE products SET affiliate_url=? WHERE product_id=?",
                     (deeplink, str(product_id))).rowcount
    conn.commit()
    conn.close()
    return bool(n)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "status":
        st = session_status()
        print("세션:", "정상" if st["ok"] else "없음", "—", st["why"])
        pend = pending_links(500)
        print(f"딥링크 필요한 상품: {len(pend)}건")
        for r in pend[:5]:
            print(f"   {r['product_id']:>12}  {r['title'][:40]}")

    elif cmd == "login":
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = _ctx(pw)
            ok = ensure_login(_page(ctx), wait_minutes=8)
            print("로그인 세션:", "저장됨" if ok else "실패")
            ctx.close()

    elif cmd == "inspect":
        inspect_ui()

    elif cmd in ("link", "linkall"):
        # link <상품ID>  /  linkall [개수]
        if cmd == "link" and len(sys.argv) > 2 and sys.argv[2].isdigit() and len(sys.argv[2]) > 5:
            pid = sys.argv[2]
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT product_id,title,detail_url FROM products WHERE product_id=?",
                (pid,)).fetchone()
            conn.close()
            if not row:
                print(f"DB 에 상품 {pid} 이(가) 없습니다.")
                sys.exit(1)
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                ctx = _ctx(pw)
                p = _page(ctx)
                try:
                    if not ensure_login(p, wait_minutes=10):
                        print("로그인 실패"); sys.exit(1)
                    print(f"\n{dict(row)['title'][:40]}")
                    link = make_deeplink(p, dict(row)["detail_url"], verbose=True)
                    if link:
                        save_link(pid, link)
                        print(f"\n✅ 저장: {link}")
                    else:
                        print("\n✘ 링크를 얻지 못했습니다")
                finally:
                    ctx.close()
        else:
            n = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else 5
            link_batch(limit=n)

    else:
        print(__doc__)
