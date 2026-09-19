"""
티스토리 글을 삭제한다. 중복 발행된 글을 정리하기 위한 도구다.

삭제는 되돌릴 수 없으므로 안전장치를 코드에 넣었다:
  1. 지우려는 글의 제목이 --expect 로 준 문자열을 포함하는지 확인한다.
     엉뚱한 글이 지워지는 사고를 막는 유일한 방법이다.
  2. 삭제 컨트롤을 찾은 내용을 먼저 전부 출력한다.
  3. --yes 를 주지 않으면 관찰만 하고 끝낸다(기본값이 관찰이다).
  4. 삭제 후 공개 페이지가 실제로 404 인지 확인한다. "지웠습니다"라는 말만 믿지 않는다.

사용법:
  python delete_tistory_post.py 3 --expect "미샤 소프트 면봉"        (관찰만)
  python delete_tistory_post.py 3 --expect "미샤 소프트 면봉" --yes  (실제 삭제)
"""
import re
import sys
import urllib.request

sys.path.insert(0, r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from playwright.sync_api import sync_playwright
import tistory_poster as T

SCAN = r"""(entryId) => {
  const rows = [...document.querySelectorAll('tr, li, .list_post .item, .post-item')]
      .filter(r => r.querySelector(`a[href*="/manage/post/${entryId}"], a[href*="/manage/newpost/${entryId}"]`));
  const all = [...document.querySelectorAll('button, a')]
      .filter(b => /삭제/.test(b.innerText || ''))
      .slice(0, 12)
      .map(b => ({tag: b.tagName, id: b.id,
                  cls: (b.className || '').toString().slice(0, 46),
                  txt: (b.innerText || '').trim().slice(0, 18)}));
  if (!rows.length) return {found: false, controls: all};
  const r = rows[0];
  const cb = r.querySelector('input[type=checkbox]');
  return {
    found: true,
    rowText: (r.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 90),
    checkbox: cb ? {id: cb.id, name: cb.name, value: cb.value} : null,
    controls: all,
  };
}"""


def public_status(entry_id: int) -> str:
    url = f"https://{T.BLOG}.tistory.com/{entry_id}"
    try:
        r = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; KakaoTalk-Scrap/1.0)"}), timeout=20)
        html = r.read().decode("utf-8", "ignore")
        t = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', html)
        return f"{r.status} · {(t.group(1) if t else '')[:50]}"
    except Exception as e:
        return f"{str(e)[:40]}"


def main() -> int:
    args = [a for a in sys.argv[1:]]
    ids = [int(a) for a in args if a.isdigit()]
    do_it = "--yes" in args
    expect = ""
    if "--expect" in args:
        i = args.index("--expect")
        if i + 1 < len(args):
            expect = args[i + 1]

    if not ids:
        print(__doc__)
        return 1
    entry_id = ids[0]

    print("=" * 64)
    print(f"  티스토리 글 삭제 {'(실행)' if do_it else '(관찰만 — 삭제하려면 --yes)'}")
    print("=" * 64)
    print(f"  대상   : /{entry_id}")
    print(f"  기대제목: {expect or '(지정 안 함 — 안전을 위해 지정을 권합니다)'}")
    print(f"  삭제 전 공개 상태: {public_status(entry_id)}")

    with sync_playwright() as pw:
        ctx = T._ctx(pw, headless=False)
        p = T._page(ctx)
        seen = []
        p.on("dialog", lambda d: (seen.append(d.message), d.accept()))
        try:
            if not T.ensure_login(p, wait_minutes=6.0):
                print("  ❌ 로그인 실패")
                return 1

            p.goto(f"https://{T.BLOG}.tistory.com/manage/posts",
                   wait_until="domcontentloaded", timeout=45000)
            p.wait_for_timeout(4500)

            info = p.evaluate(SCAN, entry_id)
            print("\n  [관찰 결과]")
            print(f"    행 발견: {info['found']}")
            if info.get("rowText"):
                print(f"    행 내용: {info['rowText']}")
            print(f"    체크박스: {info.get('checkbox')}")
            print("    삭제 컨트롤:")
            for c in info["controls"]:
                print(f"       {c}")

            if not info["found"]:
                print("\n  ⛔ 목록에서 해당 글을 찾지 못했습니다. 아무것도 하지 않습니다.")
                return 1

            # 안전장치: 제목이 기대와 다르면 절대 진행하지 않는다
            if expect and expect not in info.get("rowText", ""):
                print(f"\n  ⛔ 행 내용에 '{expect}' 가 없습니다. 다른 글일 수 있어 중단합니다.")
                return 1

            if not do_it:
                print("\n  관찰만 했습니다. 실제로 지우려면 --yes 를 붙여 다시 실행하세요.")
                return 0

            # 삭제 링크는 '행마다 하나씩' 있다(관찰 결과 a.btn_post '삭제' 가 3개).
            # 전역에서 첫 번째를 누르면 **다른 글이 지워진다.**
            # 반드시 대상 글 링크를 품은 행 안에서만 찾는다.
            clicked = p.evaluate("""(entryId) => {
                const row = [...document.querySelectorAll('tr, li, .list_post .item, .post-item')]
                    .find(r => r.querySelector(
                        `a[href*="/manage/post/${entryId}"], a[href*="/manage/newpost/${entryId}"]`));
                if (!row) return {ok:false, why:'행 없음'};
                const del = [...row.querySelectorAll('a, button')]
                    .find(b => /삭제/.test(b.innerText || ''));
                if (!del) return {ok:false, why:'행 안에 삭제 링크 없음'};
                del.click();
                return {ok:true, rowText:(row.innerText||'').replace(/\\s+/g,' ').trim().slice(0,70)};
            }""", entry_id)
            if not clicked.get("ok"):
                print(f"\n  ⛔ {clicked.get('why')} — 중단합니다.")
                return 1
            print(f"\n  삭제 클릭한 행: {clicked.get('rowText')}")
            p.wait_for_timeout(1800)
            # 확인 레이어가 뜨면 한 번 더 누른다.
            # 이때도 전역에서 '삭제' 를 찾으면 안 된다 — 목록의 다른 행 링크와 겹친다.
            # 반드시 떠 있는 모달/레이어 안에서만 찾는다.
            confirmed = p.evaluate("""() => {
                const boxes = [...document.querySelectorAll(
                    '[role=dialog], .modal, .layer, .pop_layer, .btn_group')]
                    .filter(e => e.offsetParent !== null);
                for (const box of boxes) {
                    const b = [...box.querySelectorAll('button, a')]
                        .find(x => /확인|삭제/.test(x.innerText || ''));
                    if (b) { b.click(); return {ok:true, txt:(b.innerText||'').trim().slice(0,20)}; }
                }
                return {ok:false};
            }""")
            if confirmed.get("ok"):
                print(f"  확인 레이어에서 '{confirmed['txt']}' 클릭")
                p.wait_for_timeout(2500)

            p.wait_for_timeout(3000)
            if seen:
                print(f"\n  [대화상자] {seen[-1][:70]}")
        finally:
            ctx.close()

    after = public_status(entry_id)
    print(f"\n  삭제 후 공개 상태: {after}")
    ok = "404" in after or "Not Found" in after
    print(f"  {'✅ 삭제 확인됨' if ok else '⚠️ 아직 접근됩니다 — 수동 확인이 필요합니다'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
