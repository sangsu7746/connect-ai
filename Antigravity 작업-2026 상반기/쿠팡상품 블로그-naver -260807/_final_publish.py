# -*- coding: utf-8 -*-
"""로그인 한 번으로 끝낸다 — 이미지 업로드 검증 + 본문 작성 + 발행.

배경: 티스토리 세션 쿠키는 브라우저 창을 닫으면 사라진다. 단계마다 스크립트를
나누면 매번 사람이 다시 로그인해야 한다. 그래서 하나로 합쳤다.

이미지 업로드 방식이 바뀌었다:
  기존 upload_images() 는 input[type=file] 을 찾아 파일을 주입했는데,
  현재 에디터에는 그 요소가 아예 없다(실측 0개). 이미지 관련 요소는 TinyMCE
  메뉴버튼 #mceu_0('첨부') 하나뿐이고, 메뉴에서 '사진'을 눌러야 파일 선택이 뜬다.
  그래서 DOM 을 뒤지지 않고 Playwright 의 file_chooser 로 받는다.

업로드가 실패하면 발행하지 않는다. 글자만 있는 중복 글을 또 만들지 않기 위해서다.
"""
import json
import sys

BASE = r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807"
sys.path.insert(0, BASE)
import tistory_poster as tp
import publish_generic as pg
from playwright.sync_api import sync_playwright

HANDOFF = sys.argv[1]
h = json.load(open(HANDOFF, encoding="utf-8"))
IMAGES = h.get("images") or []

MENU_ITEMS = r"""() => [...document.querySelectorAll('.mce-menu-item, [role=menuitem]')]
  .filter(e => e.offsetParent !== null)
  .map(e => (e.innerText || '').trim())
  .filter(Boolean).slice(0, 20)"""

CLICK_PHOTO = r"""() => {
  const it = [...document.querySelectorAll('.mce-menu-item, [role=menuitem]')]
    .filter(e => e.offsetParent !== null)
    .find(e => /사진|이미지/.test(e.innerText || ''));
  if (!it) return {ok: false};
  it.click();
  return {ok: true, txt: (it.innerText || '').trim()};
}"""


def upload_via_chooser(p, paths, log):
    """'첨부' 메뉴 → '사진' → 파일 선택 대화상자로 올린다. 올라간 주소를 순서대로 돌려준다."""
    before = set(p.evaluate(tp._EDITOR_IMGS_JS).get("urls") or [])
    try:
        p.click("#mceu_0", timeout=10000)
    except Exception as e:
        log(f"  첨부 메뉴를 열지 못했습니다: {str(e)[:60]}")
        return []
    p.wait_for_timeout(1200)
    log(f"  메뉴: {', '.join(p.evaluate(MENU_ITEMS)) or '(비어있음)'}")

    try:
        with p.expect_file_chooser(timeout=15000) as fc:
            r = p.evaluate(CLICK_PHOTO)
            if not r.get("ok"):
                log("  '사진' 항목을 찾지 못했습니다")
                return []
            log(f"  '{r.get('txt')}' 클릭")
        fc.value.set_files(paths)
        log(f"  파일 {len(paths)}장 전달")
    except Exception as e:
        log(f"  파일 선택 대화상자 실패: {type(e).__name__}: {str(e)[:80]}")
        return []

    # 업로드는 장당 수 초 걸린다. 전부 반영될 때까지 기다린다.
    got = []
    for _ in range(80):  # 최대 2분
        p.wait_for_timeout(1500)
        cur = [u for u in (p.evaluate(tp._EDITOR_IMGS_JS).get("urls") or []) if u not in before]
        if len(cur) >= len(paths):
            got = cur
            break
        got = cur
    log(f"  업로드 확인: {len(got)}/{len(paths)}장")
    return got


out = {}
logs = []


def log(m):
    print(m)
    logs.append(m)


with sync_playwright() as pw:
    ctx = tp._ctx(pw, headless=False)
    p = ctx.pages[0] if ctx.pages else ctx.new_page()
    p.on("dialog", lambda d: d.accept())
    try:
        if not tp.ensure_login(p, wait_minutes=float(h.get("wait_minutes", 15))):
            print(json.dumps({"ok": False, "error": "로그인 실패"}, ensure_ascii=False))
            sys.exit(0)
        p.wait_for_timeout(2000)

        urls = upload_via_chooser(p, IMAGES, log) if IMAGES else []
        out["uploaded"] = len(urls)
        if IMAGES and not urls:
            print(json.dumps({"ok": False, "error": "이미지 업로드 실패 — 발행하지 않았습니다",
                              "logs": logs}, ensure_ascii=False))
            sys.exit(0)

        html = pg._md_to_tistory_html(h["body_md"])
        html = tp._apply_uploaded(html, urls)
        # 에디터에 이미 꽂힌 이미지는 곧 setContent 로 덮인다 — 주소만 쓰고 본문은 새로 넣는다.
        res = tp._write_one(p, h["title"], html, "", h.get("mode", "public"),
                            h.get("category", ""), None,
                            {"mode": h.get("mode", "public"), "ok": False})
        out.update({"published": bool(res.get("ok")), "url": res.get("url", ""),
                    "why": res.get("why", ""), "category_ok": res.get("category_ok")})
        print(json.dumps({"ok": bool(res.get("ok")), **out, "logs": logs}, ensure_ascii=False))
    finally:
        try:
            ctx.close()
        except Exception:
            pass
