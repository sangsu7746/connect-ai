# -*- coding: utf-8 -*-
"""로그인 한 번으로 카테고리 생성 + 발행까지 끝낸다.

왜 합쳤나 — 티스토리 TSSESSION 은 세션 쿠키라 창을 닫으면 사라진다.
단계마다 스크립트를 나누면 매번 사람이 다시 로그인해야 한다.
"""
import json, sys, os
BASE = r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807"
sys.path.insert(0, BASE)
import tistory_poster as tp
from playwright.sync_api import sync_playwright

HANDOFF = sys.argv[1]
h = json.load(open(HANDOFF, encoding="utf-8"))
WANT = h.get("category") or ""

# 카테고리 관리 화면에서 '추가' 계열 컨트롤을 글자로 찾아 누른다.
FIND_ADD = r"""() => {
  const vis = e => e.offsetParent !== null;
  const all = [...document.querySelectorAll('button,a,span,div')].filter(vis);
  const hit = all.find(e => {
    const t = (e.innerText||'').trim();
    return t === '카테고리 추가' || t === '카테고리추가' || t === '+ 카테고리 추가';
  });
  if (hit) { hit.click(); return {ok:true, clicked:(hit.innerText||'').trim()}; }
  return {ok:false, sample: all.slice(0,60).map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,40)};
}"""

LIST_CATS = r"""() => {
  // 카테고리 이름은 목록 영역에 있다. 글 수 '(3)' 같은 꼬리표는 떼어낸다.
  const rows = [...document.querySelectorAll('li, tr, div')].filter(e => e.offsetParent !== null);
  const names = new Set();
  for (const e of rows) {
    if (e.children.length > 2) continue;           // 큰 컨테이너는 건너뛴다
    const t = (e.innerText || '').trim();
    if (!t || t.length > 20 || /[\r\n]/.test(t)) continue;
    const m = t.match(/^(.+?)\s*(?:\(\d+\))?$/);
    if (m && m[1] && !/^(카테고리|전체|분류|변경사항|저장|개수)/.test(m[1])) names.add(m[1].trim());
  }
  return [...names];
}"""

TYPE_NAME = r"""(name) => {
  const ins = [...document.querySelectorAll('input[type=text]')].filter(e => e.offsetParent !== null);
  // 방금 생긴 빈 입력칸이 새 카테고리 이름 자리다
  const target = ins.reverse().find(e => !e.value);
  if (!target) return {ok:false, why:'빈 입력칸 없음'};
  target.focus();
  const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
  setter.call(target, name);
  target.dispatchEvent(new Event('input', {bubbles:true}));
  target.dispatchEvent(new Event('change', {bubbles:true}));
  return {ok:true};
}"""

SAVE = r"""() => {
  const b = [...document.querySelectorAll('button')].filter(e=>e.offsetParent!==null)
    .find(e => /변경사항\s*저장|저장/.test((e.innerText||'').trim()));
  if (!b) return {ok:false};
  b.click(); return {ok:true};
}"""

out = {"category_created": False, "published": False}
with sync_playwright() as pw:
    ctx = tp._ctx(pw, headless=False)
    p = ctx.pages[0] if ctx.pages else ctx.new_page()
    p.on("dialog", lambda d: d.accept())
    try:
        if not tp.ensure_login(p, wait_minutes=6.0):
            print(json.dumps({"ok": False, "error": "로그인 실패"}, ensure_ascii=False)); sys.exit(0)

        # ── 1) 카테고리 만들기 ──────────────────────────────
        if WANT:
            p.goto(f"https://{tp.BLOG}.tistory.com/manage/category/",
                   wait_until="networkidle", timeout=45000)
            p.wait_for_timeout(4000)
            existing = [c["v"] for c in p.evaluate(LIST_CATS) if c["v"]]
            out["existing"] = existing
            if WANT in existing:
                out["category_created"] = "이미 있음"
            else:
                r = p.evaluate(FIND_ADD)
                out["add_click"] = r
                if r.get("ok"):
                    p.wait_for_timeout(1500)
                    t = p.evaluate(TYPE_NAME, WANT)
                    out["type"] = t
                    if t.get("ok"):
                        p.wait_for_timeout(800)
                        s = p.evaluate(SAVE)
                        out["save"] = s
                        p.wait_for_timeout(4000)
                        after = [c["v"] for c in p.evaluate(LIST_CATS) if c["v"]]
                        out["after"] = after
                        out["category_created"] = WANT in after

        # ── 2) 발행 ────────────────────────────────────────
        # 카테고리 화면에 머문 채로 글을 쓰려 하면 '제목 요소 없음'으로 실패한다.
        # 반드시 에디터로 돌아가서 시작한다.
        if not tp.ensure_login(p, wait_minutes=3.0):
            print(json.dumps({"ok": False, "error": "에디터 복귀 실패", **out}, ensure_ascii=False)); sys.exit(0)
        import publish_generic as pg
        html = pg._md_to_tistory_html(h["body_md"])
        res = tp._write_one(
            p, h["title"], html, "", h.get("mode", "public"),
            WANT, h.get("images") or None, {"mode": h.get("mode", "public"), "ok": False},
        )
        out["published"] = bool(res.get("ok"))
        out["url"] = res.get("url", "")
        out["why"] = res.get("why", "")
        out["uploaded"] = res.get("uploaded", 0)
        out["category_ok"] = res.get("category_ok")
    finally:
        try: ctx.close()
        except Exception: pass

print(json.dumps({"ok": out.get("published", False), **out}, ensure_ascii=False))
