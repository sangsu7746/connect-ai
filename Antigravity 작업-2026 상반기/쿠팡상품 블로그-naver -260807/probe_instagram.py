"""
인스타그램 업로드 화면의 실제 구조를 뜬다.

셀렉터를 짐작으로 고치면 실행마다 한 단계씩 진도가 나가고 끝난다.
한 번에 화면을 통째로 떠서 보고 맞춘다. 게시는 하지 않는다 — 창은 열어 둔 채 끝낸다.
"""
import io
import json
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

OUT = os.path.join(BASE_DIR, "logs", "ig_probe")


def dump(page, tag: str) -> None:
    os.makedirs(OUT, exist_ok=True)
    try:
        page.screenshot(path=os.path.join(OUT, f"{tag}.png"))
    except Exception as e:
        print(f"  스크린샷 실패: {e}")

    info = page.evaluate("""() => {
        const vis = el => {
            const r = el.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
        };
        const btns = [...document.querySelectorAll(
            'div[role="button"],button,a[role="link"],[role="menuitem"]')]
            .filter(vis)
            .map(el => ({
                tag: el.tagName,
                role: el.getAttribute('role') || '',
                aria: el.getAttribute('aria-label') || '',
                text: (el.innerText || '').trim().slice(0, 40),
            }))
            .filter(o => o.text || o.aria);
        const inputs = [...document.querySelectorAll('input')].map(el => ({
            type: el.type, accept: el.accept || '', name: el.name || '',
            hidden: !vis(el),
        }));
        const svgs = [...document.querySelectorAll('svg[aria-label]')]
            .map(el => el.getAttribute('aria-label'));
        const editable = [...document.querySelectorAll('[contenteditable="true"],textarea')]
            .map(el => ({ aria: el.getAttribute('aria-label') || '',
                          ph: el.getAttribute('placeholder') || '' }));
        return { url: location.href, btns, inputs, svgs, editable };
    }""")

    path = os.path.join(OUT, f"{tag}.json")
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(info, ensure_ascii=False, indent=2))

    print(f"\n── {tag} · {info['url']}")
    print(f"  input[type=file]: {[i for i in info['inputs'] if i['type']=='file']}")
    print(f"  svg aria-label  : {info['svgs'][:14]}")
    print(f"  편집영역        : {info['editable']}")
    print("  버튼:")
    for b in info["btns"][:26]:
        label = b["aria"] or b["text"]
        print(f"    [{b['tag']}/{b['role']}] {label}")


def main() -> int:
    from playwright.sync_api import sync_playwright
    import instagram_poster as IG

    IG._release_profile_lock(print)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            IG.PROFILE_DIR, headless=False, locale="ko-KR",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(IG.HOME, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        dump(page, "1_home")

        # 만들기 열기
        # svg 를 직접 누르면 부모 div 가 클릭을 가로챈다("intercepts pointer events").
        # :has() 로 감싼 링크를 잡아도 마찬가지였다.
        # 아이콘의 화면 좌표를 구해 그 자리를 마우스로 누른다 — 사람이 하는 것과 같다.
        opened = False
        for label in ("새로운 게시물", "New post", "만들기", "Create"):
            loc = page.locator(f'svg[aria-label="{label}"]')
            if not loc.count():
                continue
            box = loc.first.bounding_box()
            if not box:
                continue
            print(f"\n  '만들기' 진입: '{label}' 좌표 "
                  f"({box['x'] + box['width'] / 2:.0f}, {box['y'] + box['height'] / 2:.0f})")
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(3000)
            opened = True
            break
        if not opened:
            print("\n  ⛔ '만들기' 아이콘을 못 찾았습니다. 위 svg 목록을 보세요.")
            dump(page, "2_nocreate")
            ctx.close()
            return 1

        dump(page, "2_after_create")

        # 만들기를 누르면 '게시물 / 라이브 방송 / 광고' 메뉴가 펼쳐진다.
        # (릴스 항목은 없다 — 세로 영상을 게시물로 올리면 인스타가 릴스로 만든다)
        for t in ("게시물", "Post"):
            loc = page.locator(f'svg[aria-label="{t}"]')
            if not loc.count():
                continue
            box = loc.first.bounding_box()
            if not box:
                continue
            print(f"\n  하위 항목 '{t}' 클릭 "
                  f"({box['x'] + box['width'] / 2:.0f}, {box['y'] + box['height'] / 2:.0f})")
            page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(4000)
            break
        dump(page, "3_composer")

        print(f"\n결과: {OUT}")
        print("창은 열어 둡니다. 확인 후 직접 닫아 주세요.")
        page.wait_for_timeout(120000)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
