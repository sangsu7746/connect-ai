"""
tistory_poster.py
티스토리 발행 모듈 — Playwright 로 사용자 브라우저 세션을 재사용해 글을 올린다.

설계 원칙:
  · 비밀번호를 코드가 다루지 않는다. 최초 1회 사람이 직접 로그인하고,
    그 세션을 전용 프로필 폴더에 남겨 다음부터 재사용한다.
    (naver_poster.py 는 config 의 id/pw 로 로그인하지만, 그건 기존에 만들어 둔 것이고
     여기서는 그 방식을 따라가지 않는다.)
  · 기본 발행 상태는 '비공개'다. 공개 전환은 사람이 확인하고 누르는 게 맞다.
    잘못된 글이 검색에 잡히면 되돌리기 어렵다.

사용법:
  python tistory_poster.py inspect          # 편집기 DOM 구조 덤프(개발용)
  python tistory_poster.py login            # 로그인 세션 만들기/갱신
  python tistory_poster.py post <원고.md>    # 원고 파일로 비공개 발행
"""
import os
import re
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, ".tistory_profile")
BLOG = os.environ.get("TISTORY_BLOG", "headjim01")
NEWPOST_URL = f"https://{BLOG}.tistory.com/manage/newpost/"

LAUNCH_ARGS = ["--disable-blink-features=AutomationControlled", "--no-sandbox"]


def _ctx(pw, headless=False):
    os.makedirs(PROFILE_DIR, exist_ok=True)
    ctx = pw.chromium.launch_persistent_context(
        PROFILE_DIR, headless=headless, args=LAUNCH_ARGS,
        locale="ko-KR", timezone_id="Asia/Seoul", no_viewport=True,
    )
    return ctx


def _page(ctx):
    return ctx.pages[0] if ctx.pages else ctx.new_page()


def _on_editor(page) -> bool:
    """
    '로그인 페이지가 아니다' 가 아니라 '편집기가 실제로 떠 있다' 로 판정한다.

    티스토리는 카카오계정(accounts.kakao.com)으로 넘긴다. 예전 코드는 URL 에
    '/auth/login' 이 없으면 통과로 봤는데, 카카오 URL 에는 그 문자열이 없어서
    비밀번호 입력창 위에서 "로그인 확인됨" 을 출력했다.
    """
    try:
        if "/manage/newpost" not in page.url:
            return False
        return bool(page.evaluate("""() => {
            const t = document.querySelector('#post-title-inp, input[name="title"], [placeholder*="제목"]');
            const e = document.querySelector('[contenteditable="true"], textarea, iframe#editor-tistory_ifr');
            return !!(t || e);
        }"""))
    except Exception:
        return False


def ensure_login(page, wait_minutes: float = 5.0) -> bool:
    """
    글쓰기 페이지에 들어간다. 로그인 화면이면 사람이 직접 로그인할 때까지 기다린다.
    코드가 아이디·비밀번호를 입력하지 않는다 — 그건 사람이 할 일이다.
    """
    page.goto(NEWPOST_URL, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    if _on_editor(page):
        return True

    print("\n" + "=" * 62)
    print("  티스토리 로그인이 필요합니다.")
    print("  ** 지금 열린 이 창에서 ** 직접 로그인해 주세요.")
    print("  (다른 브라우저에서 한 로그인은 이 프로필에 반영되지 않습니다)")
    print("  '로그인 상태 유지'를 체크하면 다음부터 안 물어봅니다.")
    print("  비밀번호는 이 스크립트가 다루지 않습니다.")
    print(f"  최대 {wait_minutes:.0f}분 기다립니다...")
    print("=" * 62 + "\n")

    deadline = time.time() + wait_minutes * 60
    last = ""
    # 로그인 연결 재시도 횟수. 매 루프마다 누르면 의심 신호가 되지만,
    # 딱 한 번만 허용했더니 첫 시도가 타이밍이 어긋났을 때 영영 복구하지 못했다.
    relink_tries = 0
    MAX_RELINK = 3
    while time.time() < deadline:
        page.wait_for_timeout(3000)
        host = re.sub(r"^https?://([^/]+).*$", r"\1", page.url)
        if host != last:
            print(f"    현재 위치: {host}")
            last = host
        if _on_editor(page):
            print("  편집기 확인됨. 계속 진행합니다.")
            return True

        # 카카오 로그인 쿠키(_kau 등)는 살아 있는데 티스토리 세션만 끊긴 경우가 잦다.
        # 이때 www.tistory.com 에 머무르며 편집기로 못 넘어간다.
        # 로그인 버튼을 눌러 주면 이미 인증된 카카오 세션으로 자동 통과한다.
        # (비밀번호를 입력하는 게 아니라, 이미 된 로그인을 이어 붙이는 것뿐이다)
        if ("tistory.com" in host and "/manage/newpost" not in page.url
                and relink_tries < MAX_RELINK):
            relink_tries += 1
            page.wait_for_timeout(1500 * relink_tries)      # 시도할수록 간격을 벌린다
            for sel in ("a:has-text('로그인')", "button:has-text('로그인')",
                        "a[href*='auth/login']"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1200):
                        el.click()
                        print("    → 로그인 연결 시도(카카오 세션 재사용)")
                        page.wait_for_timeout(3500)
                        break
                except Exception:
                    continue
            try:
                page.goto(NEWPOST_URL, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2500)
            except Exception:
                pass

        # 카카오 동의/계속 화면이면 '계속하기' 류 버튼을 눌러 준다
        if "kakao" in host:
            for sel in ("button:has-text('계속하기')", "button:has-text('동의하고 계속하기')",
                        "a:has-text('계속하기')"):
                try:
                    el = page.locator(sel).first
                    if el.is_visible(timeout=1000):
                        el.click()
                        print("    → 카카오 계속하기 클릭")
                        page.wait_for_timeout(3000)
                        break
                except Exception:
                    continue
    print("  시간 초과 — 편집기에 도달하지 못했습니다.")
    return False


INSPECT_JS = r"""() => {
  const pick = els => [...els].slice(0, 12).map(el => ({
    tag: el.tagName,
    id: el.id || '',
    cls: (el.className || '').toString().slice(0, 46),
    name: el.getAttribute('name') || '',
    ph: el.getAttribute('placeholder') || '',
    txt: (el.innerText || el.value || '').trim().slice(0, 28),
  }));
  return {
    url: location.href,
    title: document.title,
    inputs: pick(document.querySelectorAll('input:not([type=hidden])')),
    textareas: pick(document.querySelectorAll('textarea')),
    editable: pick(document.querySelectorAll('[contenteditable="true"]')),
    iframes: [...document.querySelectorAll('iframe')].slice(0, 6)
      .map(f => ({id: f.id || '', cls: (f.className||'').toString().slice(0,40), src: (f.src||'').slice(0,60)})),
    modeBtns: [...document.querySelectorAll('*')]
      .filter(e => /기본모드|마크다운|HTML/.test((e.innerText||'').trim()) && e.children.length === 0)
      .slice(0, 8).map(e => ({tag: e.tagName, cls: (e.className||'').toString().slice(0,40), txt: (e.innerText||'').trim()})),
    tinymce: typeof window.tinymce !== 'undefined',
    editors: (typeof window.tinymce !== 'undefined') ? window.tinymce.editors.map(e => e.id) : [],
    actions: [...document.querySelectorAll('button, a, span, div, input[type=button], input[type=submit]')]
      .filter(el => el.children.length === 0)
      .map(el => ({tag: el.tagName, id: el.id || '', cls: (el.className||'').toString().slice(0,40),
                   txt: (el.innerText || el.value || '').trim().slice(0,18)}))
      .filter(o => /^(완료|발행|저장|임시저장|공개|비공개|보호|취소|미리보기)/.test(o.txt))
      .slice(0, 18),
    byId: [...document.querySelectorAll('button, a, input')]
      .filter(el => /publish|save|submit|complete|open/i.test(el.id || ''))
      .slice(0, 12).map(el => ({tag: el.tagName, id: el.id, txt: (el.innerText||el.value||'').trim().slice(0,16)})),
  };
}"""


def inspect_editor():
    """편집기 실제 구조를 덤프한다. 셀렉터를 추측하지 않기 위한 개발용."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _ctx(pw)
        p = _page(ctx)
        try:
            if not ensure_login(p, wait_minutes=8):
                return None
            p.wait_for_timeout(2500)
            info = p.evaluate(INSPECT_JS)
            print(f"URL   : {info['url']}")
            print(f"TITLE : {info['title']}")
            print(f"tinymce: {info.get('tinymce')}  editors={info.get('editors')}")
            for key in ("inputs", "textareas", "modeBtns", "actions", "byId"):
                print(f"\n[{key}]")
                for e in info.get(key, []):
                    print("   ", {k: v for k, v in e.items() if v})
            print("\n[iframes]")
            for f in info.get("iframes", []):
                print("   ", f)
            return info
        finally:
            ctx.close()


def session_status(quick: bool = False) -> dict:
    """
    로그인이 살아 있는지 알려준다. 기본값은 실제로 편집기까지 들어가 보는 검증이다.

    구조상 티스토리 세션(TSSESSION)은 세션 쿠키라 브라우저를 닫으면 매번 사라진다.
    남는 건 카카오 쿠키(_kau/_kawlt 등)뿐이고, ensure_login 이 그걸로 이어 붙인다.

    그런데 카카오 쿠키가 만료 전이어도 이어 붙이기가 실패하는 경우가 실제로 있었다
    (쿠키 28일 남음인데 편집기 진입 실패). 그래서 쿠키 만료일만 보고 '정상'이라고
    답하면 안 된다 — 그 답을 믿고 발행을 걸면 로그인 화면 앞에서 멈춘다.
    quick=True 는 브라우저를 띄우지 않는 힌트일 뿐, 로그인 보장이 아니다.
    """
    import sqlite3
    import shutil
    import tempfile
    from datetime import datetime, timezone, timedelta

    src = os.path.join(PROFILE_DIR, "Default", "Network", "Cookies")
    if not os.path.exists(src):
        src = os.path.join(PROFILE_DIR, "Default", "Cookies")
    if not os.path.exists(src):
        return {"ok": False, "why": "프로필 없음 — 최초 로그인이 필요합니다", "days": 0}

    tmp = os.path.join(tempfile.gettempdir(), "_tistory_ck.db")
    try:
        shutil.copy2(src, tmp)
        conn = sqlite3.connect(tmp)
        rows = conn.execute(
            "SELECT name, expires_utc FROM cookies "
            "WHERE host_key LIKE '%kakao%' AND name IN ('_kau','_kawlt','_kaslt','_kahai')"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "why": f"쿠키 확인 실패: {e}", "days": 0}

    if not rows:
        return {"ok": False, "why": "카카오 로그인 쿠키 없음 — 로그인이 필요합니다", "days": 0}

    epoch = datetime(1601, 1, 1, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    days = []
    for _, exp in rows:
        if exp:
            days.append((epoch + timedelta(microseconds=exp) - now).days)
    left = min(days) if days else 0
    if quick:
        return {"ok": left > 0, "days": left, "verified": False,
                "why": "쿠키 남음(미검증)" if left > 3 else "곧 만료 — 다시 로그인해 두세요"}

    if left <= 0:
        return {"ok": False, "days": 0, "verified": True,
                "why": "카카오 쿠키 만료 — 로그인이 필요합니다"}

    # 여기서부터가 진짜 확인이다. 편집기가 뜨는지 직접 본다.
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless=True)
        p = _page(ctx)
        try:
            p.goto(NEWPOST_URL, wait_until="domcontentloaded", timeout=45000)
            p.wait_for_timeout(3500)
            ok = _on_editor(p)
        except Exception as e:
            return {"ok": False, "days": left, "verified": True,
                    "why": f"확인 실패: {str(e)[:50]}"}
        finally:
            ctx.close()
    return {"ok": ok, "days": left, "verified": True,
            "why": "정상" if ok else f"쿠키는 {left}일 남았지만 세션이 끊김 — 로그인이 필요합니다"}


def keepalive(headless: bool = True) -> bool:
    """
    세션을 살려 두기 위해 주기적으로 실행한다(스케줄러에 걸어 두면 좋다).
    카카오 쿠키는 쓸 때마다 갱신되므로, 가끔 들르는 것만으로 만료를 미룰 수 있다.
    """
    from playwright.sync_api import sync_playwright
    st = session_status(quick=True)      # 아래에서 어차피 실제로 들어가 본다
    print(f"[세션] 쿠키 잔여 약 {st['days']}일 — {st['why']}")
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless)
        p = _page(ctx)
        try:
            ok = ensure_login(p, wait_minutes=0.1)   # 사람을 기다리지 않는다
            print("[세션]", "갱신됨" if ok else "만료 — 직접 로그인이 필요합니다")
            if not ok:
                try:
                    import notify
                    notify.send("⚠️ 티스토리 로그인이 만료됐습니다.\n"
                                "아래 명령을 실행해 다시 로그인해 주세요:\n"
                                "python tistory_poster.py login")
                except Exception:
                    pass
            return ok
        finally:
            ctx.close()


def build_html(post: dict, product: dict, affiliate_url: str = "",
               upload_slots: int = 0) -> str:
    """
    원고 + 상품 이미지 + 고지를 티스토리 본문 HTML 로 만든다.

    티스토리는 HTML 을 직접 넣을 수 있어서 쿠팡 CDN 주소를 그대로 참조해도 보이긴 한다.
    다만 그러면 대표이미지(og:image)가 티스토리 기본 로고로 남는다 — 티스토리는
    자기 서버에 올라온 이미지 중에서만 대표이미지를 고르기 때문이다.
    upload_slots > 0 이면 {{IMG0}}.. 자리표시자를 넣고, write_post 가 업로드 후 채운다.
    가격 그래프는 로컬 PNG 라 외부에서 접근할 수 없어 여기서는 넣지 않는다.
    """
    from datetime import datetime as _dt
    import json as _json

    disclosure = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."

    imgs = product.get("detail_images") or []
    if isinstance(imgs, str):
        try:
            imgs = _json.loads(imgs)
        except Exception:
            imgs = []
    main = product.get("image_url")
    if main:
        imgs = [main] + [u for u in imgs if u != main]
    imgs = [u for u in dict.fromkeys(imgs) if u and "/image/displayitem" not in u][:3]
    if upload_slots > 0:
        # 자리표시자에 **원래 쿠팡 주소를 함께 담는다.**
        # 업로드가 실패했을 때 되돌아갈 곳이 없으면 이미지가 통째로 사라진다 —
        # 실제로 티스토리 10건이 이미지 0장으로 나갔다.
        # 티스토리 업로드가 되면 대표이미지까지 잡히고, 안 되면 최소한 본문 이미지는 보인다.
        imgs = ["{{IMG%d|%s}}" % (i, u) for i, u in enumerate(imgs[:min(upload_slots, 3)])]

    # 본문을 문단으로 쪼개고 링크·고지 줄은 걷어낸다(아래에서 다시 붙인다)
    paras = []
    for block in re.split(r"\n\s*\n", (post.get("content") or "").strip()):
        keep = []
        for line in block.split("\n"):
            s = line.strip()
            if not s or disclosure in s:
                continue
            if re.match(r"^\[?구매\s*링크", s) or re.match(r"^https?://", s):
                continue
            if "coupang.com" in s and len(s) < 120:
                continue
            keep.append(s)
        if keep:
            # 줄을 공백으로 이어붙이지 않는다. 예전엔 " ".join(keep) 이라
            # 모델이 '## 소제목'이나 '- 목록'을 내놔도 산문으로 뭉개졌다.
            # 티스토리는 HTML 을 직접 넣을 수 있으니 구조를 살리는 게 맞다.
            paras.append(keep)

    def esc(s):
        return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))

    def render_block(lines: list) -> list:
        """한 문단(줄 목록)을 HTML 로 바꾼다. 소제목과 목록을 살린다."""
        html, bullets = [], []

        def flush():
            if bullets:
                items = "".join(f"<li>{esc(b)}</li>" for b in bullets)
                html.append(f'<ul {P}>{items}</ul>')
                bullets.clear()

        prose = []
        for ln in lines:
            if re.match(r"^#{2,3}\s+", ln):
                flush()
                if prose:
                    html.append(f'<p {P}>{esc(" ".join(prose))}</p>')
                    prose = []
                # 생성형 검색은 소제목 단위로 문서를 쪼개 읽는다. h2 로 살려 준다.
                html.append(f'<h2 data-ke-size="size23">{esc(re.sub(r"^#+\s+", "", ln))}</h2>')
            elif re.match(r"^[-*•]\s+", ln):
                if prose:
                    html.append(f'<p {P}>{esc(" ".join(prose))}</p>')
                    prose = []
                bullets.append(re.sub(r"^[-*•]\s+", "", ln))
            else:
                flush()
                prose.append(ln)
        flush()
        if prose:
            html.append(f'<p {P}>{esc(" ".join(prose))}</p>')
        return html

    P = 'data-ke-size="size16"'
    out, img_i = [], 0
    # 대가성 고지는 맨 위, 본문과 같은 크기·색으로. (예전엔 맨 끝에 회색 작은 글씨였다)
    out.append(f'<p {P}>{disclosure}</p>')
    slots = {1, 3} if len(paras) > 3 else {1}
    for i, para in enumerate(paras):
        out.extend(render_block(para))
        if i in slots and img_i < len(imgs):
            out.append(
                f'<p {P}><img src="{imgs[img_i]}" alt="{esc(product.get("title", "")[:40])}" '
                'style="max-width:100%;height:auto;" /></p>'
            )
            img_i += 1
    while img_i < len(imgs):
        out.append(f'<p {P}><img src="{imgs[img_i]}" style="max-width:100%;height:auto;" /></p>')
        img_i += 1

    # 발행일이 아니라 '실제로 확인한 시각'을 쓴다. 08-11 에 본 값을 08-13 에 올리면서
    # "08월 13일 기준"이라고 적으면 그건 틀린 정보다.
    import sys as _sys
    _sys.path.insert(0, BASE_DIR)
    from coupang_blog_pipeline import _fmt_observed
    when = _fmt_observed(product.get("updated_at", ""))
    out.append(
        f'<p data-ke-size="size15"><span style="color:#888;">'
        f'※ 위 가격은 {when} 쿠팡 판매 페이지에서 확인한 값입니다. '
        '쿠팡 판매가는 수시로 변동되므로, 구매 시점에 실제 가격을 반드시 확인해 주세요.'
        '</span></p>'
    )
    if affiliate_url:
        out.append(f'<p {P}>&nbsp;</p>')
        out.append(
            # '최저가'라고 쓰지 않는다 — 확인할 수 없는 주장이고, 스스로 정한 금지어다.
            f'<p {P}><strong><a href="{affiliate_url}" target="_blank" rel="nofollow noopener">'
            '▶ 쿠팡에서 현재 가격 확인하기</a></strong></p>'
        )
    out.append(f'<p {P}>&nbsp;</p>')
    out.append(f'<p data-ke-size="size15"><span style="color:#999;">{disclosure}</span></p>')
    return "\n".join(out)


def text_to_html(text: str, affiliate_url: str = "") -> str:
    """
    원고(평문)를 티스토리 본문 HTML 로 바꾼다.

    generate_post_draft 가 내놓는 원고는 빈 줄로 문단이 나뉜 평문이다.
    그대로 넣으면 줄바꿈이 다 사라지므로 문단마다 <p> 로 감싼다.
    쿠팡 링크는 클릭 가능한 <a> 로 만들고, 파트너스 고지는 눈에 띄게 분리한다.
    """
    disclosure = "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
    # 고지는 맨 위, 본문과 같은 크기·색으로. (아래에서 한 번 더 반복한다)
    out = [f'<p data-ke-size="size16">{disclosure}</p>']
    for block in re.split(r"\n\s*\n", (text or "").strip()):
        b = block.strip()
        if not b:
            continue
        if disclosure in b:
            continue                      # 맨 끝에 따로 붙인다
        if re.match(r"^https?://", b):
            continue                      # 링크 줄은 버튼으로 대체
        if b.startswith("[구매 링크]") or b.startswith("구매 링크:"):
            continue
        b = (b.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace("\n", "<br>"))
        out.append(f'<p data-ke-size="size16">{b}</p>')

    if affiliate_url:
        out.append(
            '<p data-ke-size="size16">&nbsp;</p>'
            f'<p data-ke-size="size16"><a href="{affiliate_url}" target="_blank" '
            'rel="nofollow noopener">▶ 쿠팡에서 상품 보러가기</a></p>'
        )
    out.append('<p data-ke-size="size16">&nbsp;</p>')
    out.append(f'<p data-ke-size="size15"><span style="color:#999;">{disclosure}</span></p>')
    return "\n".join(out)


_SELECT_CATEGORY_JS = r"""(target) => {
  const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
  const btn = document.querySelector('#category-btn');
  if (!btn) return {ok:false, why:'category-btn 없음'};
  btn.click();
  return {ok:true, opened:true};
}"""

_PICK_CATEGORY_JS = r"""(target) => {
  const vis = e => e && (e.offsetParent !== null || e.getClientRects().length);
  // 네이버에서 배운 방식: 태그를 가정하지 말고 목록 컨테이너의 자식을 항목으로 본다.
  // 실측: 목록 컨테이너는 div#category-list 이고 항목은 li 가 아니라
  // div.mce-menu-item 이다(TinyMCE 메뉴). 태그를 가정하면 하나도 못 찾는다.
  const cont = document.querySelector('#category-list');
  let items = cont ? [...cont.children].filter(vis) : [];
  if (!items.length) {
    items = [...document.querySelectorAll('.mce-menu-item')].filter(vis);
  }
  const names = [];
  let hit = null;
  for (const li of items) {
    const lines = (li.innerText || '').trim().split('\n')
                    .map(s => s.replace(/ /g, ' ').trim()).filter(Boolean);
    if (!lines.length) continue;
    const nm = lines[lines.length - 1];
    names.push(nm);
    if (nm === target && !hit) hit = li;
  }
  if (hit) {
    (hit.querySelector('a, button, label, span') || hit).click();
    return {ok: true, names};
  }
  return {ok: false, names};
}"""


#: 파이프라인의 표준 카테고리명(네이버 기준) → 티스토리에 실제로 만들어 둔 이름.
#: 티스토리 카테고리는 슬래시 없이 공백으로 만들어져 있어 그대로 넘기면 못 찾는다.
TISTORY_ALIAS = {
    "스포츠/레저": "스포츠 레저",
    "도서/음반/DVD": "도서 음반 DVD",
    "헬스/건강식품": "헬스 건강식품",
}


def to_tistory_category(name: str) -> str:
    """표준 카테고리명을 티스토리에 있는 이름으로 바꾼다."""
    return TISTORY_ALIAS.get(name, name)


def select_category(page, name: str, log=print) -> bool:
    """
    티스토리 카테고리를 고른다. 실패해도 예외를 올리지 않는다.

    실측(2026-08): 카테고리는 '발행 레이어'가 아니라 에디터 상단
    button#category-btn 에 있다. 발행 레이어의 <dt>기본</dt> 은 카테고리가 아니라
    '기본 설정' 섹션 제목이라 그걸 눌러 봐야 아무 목록도 안 나온다.
    """
    if not name:
        return False
    try:
        r = page.evaluate(_SELECT_CATEGORY_JS, name)
        if not r.get("ok"):
            log(f"  카테고리 버튼 없음: {r.get('why')}")
            return False
        page.wait_for_timeout(1500)
        r2 = page.evaluate(_PICK_CATEGORY_JS, name)
        names = r2.get("names") or []
        if not names:
            log("  ⚠️ 카테고리 목록이 비어 있습니다 — 티스토리에 카테고리를 먼저 만들어야 합니다")
            return False
        log(f"  목록 {len(names)}개: {', '.join(names[:16])}")
        if r2.get("ok"):
            log(f"  ✅ 카테고리 '{name}' 선택")
            return True
        log(f"  ⚠️ '{name}' 없음 — 기본 분류로 저장됩니다")
        return False
    except Exception as e:
        log(f"  카테고리 선택 건너뜀: {str(e)[:60]}")
        return False


_FILL_JS = r"""([title, html]) => {
  const t = document.querySelector('#post-title-inp');
  if (!t) return {ok:false, why:'제목 요소 없음'};
  const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype,'value').set;
  setter.call(t, title);
  t.dispatchEvent(new Event('input', {bubbles:true}));
  t.dispatchEvent(new Event('change', {bubbles:true}));

  if (typeof window.tinymce === 'undefined') return {ok:false, why:'tinymce 없음'};
  const ed = window.tinymce.get('editor-tistory') || window.tinymce.activeEditor;
  if (!ed) return {ok:false, why:'에디터 인스턴스 없음'};
  ed.setContent(html);
  ed.fire('change');
  try { ed.save(); } catch(e) {}
  return {ok:true, titleLen: t.value.length, bodyLen: ed.getContent().length};
}"""


_EDITOR_IMGS_JS = r"""() => {
  const ed = window.tinymce && (window.tinymce.get('editor-tistory') || window.tinymce.activeEditor);
  if (!ed) return {ok:false, urls:[], tokens:[]};
  const body = ed.getBody();
  const urls = [...body.querySelectorAll('img')].map(i => i.getAttribute('src') || '')
                 .filter(s => /kakaocdn|daumcdn|tistory/.test(s));
  const raw = ed.getContent({format:'raw'}) || '';
  const tokens = (raw.match(/\[##_Image\|[^\]]*?\|_##\]/g) || []);
  return {ok:true, urls, tokens};
}"""


def upload_images(page, paths, log=print, timeout_s: int = 90) -> list:
    """
    로컬 이미지를 티스토리에 업로드하고, 본문에 꽂힌 주소를 순서대로 돌려준다.

    왜 필요한가: 티스토리 대표이미지(og:image)는 '티스토리에 올라간 이미지' 중에서만
    고른다. 본문이 쿠팡 CDN 주소를 <img> 로 참조만 하면 후보가 하나도 없어서
    대표이미지가 티스토리 기본 로고로 남는다 — 실측으로 확인한 실제 증상이다.
    (opengraph.png, 6.9KB 가 두 글 모두의 og:image 였다)
    """
    paths = [p for p in (paths or []) if p and os.path.exists(p)]
    if not paths:
        return []

    before = page.evaluate(_EDITOR_IMGS_JS)
    if not before.get("ok"):
        log("  이미지 업로드 건너뜀: 에디터 인스턴스를 찾지 못했습니다")
        return []
    seen = set(before.get("urls") or [])

    # 파일 입력을 '숨김이 아닌 것'으로 거르면 안 된다 — 티스토리 업로드 입력은 항상 숨어 있다.
    inputs = page.query_selector_all("input[type=file]")
    cands = []
    for el in inputs:
        try:
            acc = (el.get_attribute("accept") or "").lower()
        except Exception:
            continue
        if acc == "" or "image" in acc or any(x in acc for x in (".jpg", ".png", ".jpeg", ".gif")):
            cands.append(el)
    log(f"  파일 입력 {len(inputs)}개 중 이미지용 후보 {len(cands)}개")
    if not cands:
        log("  ⚠️ 업로드 입력을 찾지 못했습니다 — 대표이미지 없이 진행합니다")
        return []

    for idx, el in enumerate(cands):
        try:
            el.set_input_files(paths)
        except Exception as e:
            log(f"  입력 {idx} 설정 실패: {str(e)[:60]}")
            continue

        deadline = time.time() + timeout_s
        got = []
        while time.time() < deadline:
            page.wait_for_timeout(1500)
            cur = page.evaluate(_EDITOR_IMGS_JS)
            got = [u for u in (cur.get("urls") or []) if u not in seen]
            if len(got) >= len(paths):
                break
        if got:
            log(f"  ✅ 이미지 {len(got)}/{len(paths)}장 업로드됨")
            return got
        log(f"  입력 {idx}: 업로드 반응 없음 — 다음 후보 시도")

    log("  ⚠️ 업로드된 이미지를 확인하지 못했습니다 — 대표이미지 없이 진행합니다")
    return []


def _apply_uploaded(html: str, urls: list) -> str:
    """
    `{{IMGn|폴백주소}}` 자리표시자를 실제 주소로 바꾼다.

    업로드된 주소가 있으면 그것을 쓰고, 없으면 자리표시자에 담아 둔 쿠팡 주소로 되돌린다.
    예전에는 못 채운 자리의 <p> 를 지웠는데, 업로드가 실패하자 본문 이미지가
    전부 사라진 채로 10건이 발행됐다. 썸네일을 얻으려다 이미지를 잃는 건 손해다.
    """
    def repl(m):
        i, fallback = int(m.group(1)), m.group(2)
        return urls[i] if i < len(urls) and urls[i] else fallback

    html = re.sub(r"\{\{IMG(\d+)\|([^}]*)\}\}", repl, html)
    # 폴백 주소조차 비어 있던 자리는 어쩔 수 없이 지운다
    return re.sub(r"<p[^>]*>\s*<img[^>]*src=\"\"[^>]*>\s*</p>\s*", "", html)


EDIT_URL = f"https://{BLOG}.tistory.com/manage/newpost/{{id}}?type=post&returnURL=%2Fmanage%2Fposts"

_READ_JS = r"""() => {
  const t = document.querySelector('#post-title-inp');
  const ed = window.tinymce && (window.tinymce.get('editor-tistory') || window.tinymce.activeEditor);
  if (!t || !ed) return null;
  return {title: t.value, html: ed.getContent()};
}"""


def fix_disclosure_html(html: str, disclosure: str) -> str:
    """
    이미 발행된 글의 HTML 에서 대가성 고지를 맨 위로 올린다.

    파트너스 최종 승인 반려 사유가 정확히 이것이었다 —
    "대가성 문구는 활동 게시물 최상단". 기존 글은 고지가 본문 1만 자 뒤에 있었다.
    """
    # 이미 첫 블록이면 그대로 둔다
    blocks = [b for b in re.split(r"(?=<p|<h\d|<ul|<ol|<figure|<div)", html) if b.strip()]
    if blocks and disclosure in blocks[0]:
        return html

    # 기존 고지 줄을 걷어낸다(맨 끝의 회색 작은 글씨 포함)
    kept = [b for b in blocks if disclosure not in b]
    top = f'<p data-ke-size="size16">{disclosure}</p>'
    # 맨 끝에도 한 번 더 남겨 둔다(중복 표기는 문제되지 않는다)
    bottom = f'<p data-ke-size="size15"><span style="color:#999;">{disclosure}</span></p>'
    return top + "".join(kept) + bottom


def swap_affiliate(html: str, deeplink: str) -> str:
    """본문의 쿠팡 상품 주소를 파트너스 딥링크로 바꾼다. 추적 코드가 없으면 수수료가 0원이다."""
    if not deeplink or "link.coupang.com" not in deeplink:
        return html
    # <a href="..."> 안의 쿠팡 주소
    html = re.sub(r'href="https?://(?:www\.)?coupang\.com/[^"]*"', f'href="{deeplink}"', html)
    # 평문으로 노출된 주소
    html = re.sub(r'https?://(?:www\.)?coupang\.com/vp/products/\S*', deeplink, html)
    return html


def _edit_one(p, entry_id: int, transform, mode: str, log) -> dict:
    """이미 로그인된 page 로 글 하나를 고친다. 브라우저 수명은 호출자가 관리한다."""
    result = {"entry_id": entry_id, "ok": False}
    p.goto(EDIT_URL.format(id=entry_id), wait_until="domcontentloaded", timeout=45000)
    p.wait_for_timeout(5000)
    # '이어서 작성하시겠습니까' 류 팝업
    for txt in ("취소", "확인"):
        try:
            b = p.locator(f"button:has-text('{txt}')").first
            if b.is_visible(timeout=1000):
                b.click()
                p.wait_for_timeout(700)
                break
        except Exception:
            pass

    cur = p.evaluate(_READ_JS)
    if not cur:
        result["why"] = "수정 화면에서 제목/본문을 읽지 못했습니다"
        return result
    log(f"  현재 제목: {cur['title'][:46]}")
    log(f"  현재 본문: {len(cur['html'])}자")

    new_title, new_html = transform(cur["title"], cur["html"])
    if new_title == cur["title"] and new_html == cur["html"]:
        result.update(ok=True, note="바꿀 것이 없어 저장하지 않았습니다")
        return result

    r = p.evaluate(_FILL_JS, [new_title, new_html])
    if not r.get("ok"):
        result["why"] = f"입력 실패: {r.get('why')}"
        return result
    log(f"  새 제목  : {new_title[:46]}")
    log(f"  새 본문  : {r['bodyLen']}자")

    p.locator("#publish-layer-btn").click()
    p.wait_for_timeout(2000)
    radio_id = "#open0" if mode == "private" else "#open20"
    try:
        p.evaluate("""(rid) => {
            const inp = document.querySelector(rid);
            if (!inp) return false;
            (document.querySelector(`label[for="${rid.slice(1)}"]`) || inp).click();
            return true;
        }""", radio_id)
        p.wait_for_timeout(800)
    except Exception:
        pass

    p.locator("#publish-btn").click()
    p.wait_for_timeout(6000)
    done = "/manage/newpost" not in p.url
    result.update(ok=done, url=p.url,
                  note="수정 완료" if done else "저장 클릭했으나 편집기에 남아 있음")
    return result


def edit_posts(jobs: dict, mode: str = "public", headless: bool = False, log=print) -> dict:
    """
    여러 글을 **한 브라우저 세션에서** 연속으로 고친다.

    글마다 브라우저를 새로 열면 안 된다. 티스토리 세션 쿠키(TSSESSION)는 세션 쿠키라
    창을 닫는 순간 사라지고, 두 번째 글부터 로그인 화면에 막힌다 — 실제로 그렇게 실패했다.
    (첫 글은 성공, 두 번째 글은 "시간 초과 — 편집기에 도달하지 못했습니다")

    jobs: {글번호: transform 함수}
    """
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless)
        p = _page(ctx)
        p.on("dialog", lambda d: d.accept())
        try:
            if not ensure_login(p, wait_minutes=6):
                return {k: {"ok": False, "why": "로그인/편집기 도달 실패"} for k in jobs}
            for entry_id, transform in sorted(jobs.items()):
                log(f"\n[{entry_id}]")
                try:
                    out[entry_id] = _edit_one(p, entry_id, transform, mode, log)
                except Exception as e:
                    out[entry_id] = {"ok": False, "why": str(e)[:120]}
                p.wait_for_timeout(1500)
            return out
        finally:
            ctx.close()


def write_post(title: str, content: str, tags: str = "", affiliate_url: str = "",
               mode: str = "draft", headless: bool = False,
               prebuilt_html: bool = False, category: str = "",
               upload_paths: list = None) -> dict:
    """
    티스토리에 글을 올린다.

    mode:
      draft   임시저장  (기본값 — 되돌리기 쉽고 검색에 노출되지 않는다)
      private 비공개 발행
      public  공개 발행  (호출자가 명시적으로 지정해야만 한다)

    기본값을 draft 로 둔 이유: 잘못된 글이 공개로 올라가 검색에 잡히면
    되돌리기 어렵다. 첫 발행은 사람이 눈으로 확인하고 공개하는 게 맞다.
    """
    from playwright.sync_api import sync_playwright
    if mode not in ("draft", "private", "public"):
        raise ValueError(f"mode 는 draft/private/public 중 하나여야 합니다: {mode}")

    html = content if prebuilt_html else text_to_html(content, affiliate_url)
    result = {"mode": mode, "ok": False}

    with sync_playwright() as pw:
        ctx = _ctx(pw, headless)
        p = _page(ctx)
        try:
            if not ensure_login(p, wait_minutes=6):
                result["why"] = "로그인/편집기 도달 실패"
                return result
            return _write_one(p, title, html, tags, mode, category, upload_paths, result)
        finally:
            ctx.close()


def _write_one(p, title: str, html: str, tags: str, mode: str,
               category: str, upload_paths: list, result: dict) -> dict:
    """
    이미 로그인된 page 로 글 하나를 올린다. 브라우저 수명은 호출자가 관리한다.

    write_posts() 가 여러 건을 한 세션에서 돌리려고 갈라 놓은 것이다.
    글마다 브라우저를 새로 열면 티스토리 세션 쿠키가 사라져 두 번째부터 로그인 화면에 막힌다.
    """
    p.wait_for_timeout(2000)
    # 이어쓰기 안내 팝업이 뜨면 닫는다(이전 임시저장이 있을 때 나온다)
    for txt in ("취소", "새로 작성"):
        try:
            btn = p.locator(f"button:has-text('{txt}')").first
            if btn.is_visible(timeout=1200):
                btn.click()
                p.wait_for_timeout(800)
                break
        except Exception:
            pass

    # 이미지 업로드가 먼저다. setContent 를 하면 에디터 내용이 통째로 덮여서
    # 그 전에 올려 둔 이미지가 사라진다. 주소만 받아 두고 본문에 끼워 넣는다.
    if upload_paths:
        urls = upload_images(p, upload_paths)
        html = _apply_uploaded(html, urls)
        result["uploaded"] = len(urls)

    r = p.evaluate(_FILL_JS, [title, html])
    if not r.get("ok"):
        result["why"] = f"본문 입력 실패: {r.get('why')}"
        return result
    print(f"  제목 {r['titleLen']}자 / 본문 {r['bodyLen']}자 입력됨")

    if category:
        result["category_ok"] = select_category(p, category)

    if tags:
        try:
            tag_el = p.locator("#tagText")
            for t in [x.strip() for x in tags.split(",") if x.strip()][:8]:
                tag_el.click()
                tag_el.type(t, delay=40)
                p.keyboard.press("Enter")
                p.wait_for_timeout(250)
        except Exception as e:
            print(f"  태그 입력 건너뜀: {str(e)[:50]}")

    p.wait_for_timeout(600)

    if mode == "draft":
        # 주의: 임시저장은 '글'로 등록되지 않는다. 글 관리 목록에 안 뜨고
        # 에디터 안의 임시저장 목록에만 쌓인다(카운터로 확인됨).
        p.locator("a.action:has-text('임시저장')").first.click()
        p.wait_for_timeout(3000)
        result.update(ok=True, url=p.url,
                      note="임시저장됨 — 글 관리에는 나오지 않습니다. "
                           "글로 등록하려면 mode='private' 또는 'public' 을 쓰세요")
        return result

    # ── 발행 레이어 열기 ──────────────────────────────────────
    # 실측으로 확보한 ID (2026-08):
    #   #publish-layer-btn  완료 → 레이어 열기
    #   #open20 공개 / #open15 공개(보호) / #open0 비공개  (radio)
    #   #publish-btn        최종 저장 (선택한 공개설정에 따라 라벨이 바뀐다)
    p.locator("#publish-layer-btn").click()
    p.wait_for_timeout(2000)

    radio_id = "#open0" if mode == "private" else "#open20"
    try:
        # 라디오는 label 을 눌러야 반응한다
        p.evaluate("""(rid) => {
            const inp = document.querySelector(rid);
            if (!inp) return false;
            const lab = document.querySelector(`label[for="${rid.slice(1)}"]`) || inp;
            lab.click();
            return true;
        }""", radio_id)
        p.wait_for_timeout(800)
    except Exception as e:
        print(f"  공개설정 클릭 실패: {str(e)[:60]}")

    btn_label = p.evaluate("""() => {
        const b = document.querySelector('#publish-btn');
        return b ? (b.innerText||'').trim() : '';}""")
    print(f"  최종 버튼: '{btn_label}'")

    p.locator("#publish-btn").click()
    p.wait_for_timeout(6000)

    # 발행되면 에디터를 벗어난다 — URL 로 성공을 판정한다
    done = "/manage/newpost" not in p.url
    result.update(ok=done, url=p.url,
                  note=("발행 완료" if done else
                        "최종 저장 클릭했으나 편집기에 남아 있음 — 확인 필요"))
    return result


def write_posts(jobs: list, mode: str = "public", headless: bool = False, log=print,
                wait_minutes: float = 12.0) -> dict:
    """
    여러 글을 **한 브라우저 세션에서** 연속 발행한다.

    티스토리 세션 쿠키(TSSESSION)는 창을 닫으면 사라진다. 글마다 write_post 를 부르면
    두 번째부터 로그인 화면에 막힌다 — 수정 작업에서 실제로 그렇게 실패했다.
    그래서 로그인 한 번에 전부 처리한다.

    jobs: [{"key":..., "title":..., "html":..., "tags":..., "category":...,
            "upload_paths":[...]}, ...]
    """
    from playwright.sync_api import sync_playwright
    out = {}
    with sync_playwright() as pw:
        ctx = _ctx(pw, headless)
        p = _page(ctx)
        p.on("dialog", lambda d: d.accept())
        try:
            if not ensure_login(p, wait_minutes=wait_minutes):
                return {j["key"]: {"ok": False, "why": "로그인/편집기 도달 실패"} for j in jobs}
            for i, j in enumerate(jobs, 1):
                log(f"\n[{i}/{len(jobs)}] {j['title'][:44]}")
                try:
                    out[j["key"]] = _write_one(
                        p, j["title"], j["html"], j.get("tags", ""), mode,
                        j.get("category", ""), j.get("upload_paths"), {"mode": mode, "ok": False})
                except Exception as e:
                    out[j["key"]] = {"ok": False, "why": str(e)[:140]}
                    log(f"  ✘ {str(e)[:90]}")
                # 다음 글을 위해 새 글쓰기 화면으로 돌아간다
                if i < len(jobs):
                    p.wait_for_timeout(2500)
                    try:
                        p.goto(NEWPOST_URL, wait_until="domcontentloaded", timeout=45000)
                        p.wait_for_timeout(4000)
                    except Exception:
                        pass
            return out
        finally:
            ctx.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "inspect"
    if cmd == "inspect":
        inspect_editor()
    elif cmd == "post":
        # 사용법: post <상품ID> [draft|private|public]
        if len(sys.argv) < 3:
            print("사용법: python tistory_poster.py post <상품ID> [draft|private|public]")
            sys.exit(1)
        pid = sys.argv[2]
        mode = sys.argv[3] if len(sys.argv) > 3 else "draft"

        sys.path.insert(0, BASE_DIR)
        import coupang_blog_pipeline as pipeline
        import coupang_collector as collector

        prod = next((x for x in collector.get_all_products_from_db()
                     if str(x["product_id"]) == str(pid)), None)
        if not prod:
            print(f"DB 에 상품 {pid} 이(가) 없습니다.")
            sys.exit(1)

        # 난수 데이터 상품과 중복 발행을 막는다. 실제로 /2 와 /3 에 같은 글이 나갔다.
        guard = pipeline.check_publishable(pid, "tistory")
        if not guard["ok"]:
            print(f"⛔ 발행 중단: {guard['why']}")
            sys.exit(1)

        aff = prod.get("affiliate_url") or ""
        if "link.coupang.com" not in aff:
            print("\n  [주의] 파트너스 딥링크가 아닙니다. 이대로 발행하면 수수료가 0원입니다.")
            print(f"         현재 링크: {aff[:70]}")
            print("         setlink 명령으로 딥링크를 먼저 넣는 것을 권합니다.\n")

        print("원고 생성 중...")
        post = pipeline.generate_post_draft(pid)
        print(f"제목: {post['title']}")

        # 원고 검사. 네이버 쪽에만 걸려 있고 티스토리는 통과였다 —
        # generate_post_draft 가 post["guard"] 를 만들어 두는데 아무도 안 봤다.
        import guardrails
        g = guardrails.check(post["content"], post.get("context", ""), post["title"])
        if not g["ok"]:
            print("⛔ 원고 검사 실패 — 발행하지 않습니다:")
            for b in g["blocking"][:8]:
                print(f"    {b}")
            sys.exit(1)

        # 대표이미지를 만들려면 티스토리에 실제로 올라간 이미지가 있어야 한다.
        img_paths = pipeline.prepare_images(prod, 3)
        html = build_html(post, prod, aff, upload_slots=len(img_paths))

        # 파트너스 승인 기준을 실제 발행 HTML 로 검사한다(태그 제거 후 평문으로).
        plain = re.sub(r"<[^>]+>", " ", html)
        probs = guardrails.check_disclosure(plain, pipeline.ad_title(post["title"]))
        if probs:
            print("⛔ 파트너스 표시 기준 위반 — 발행하지 않습니다:")
            for x in probs:
                print(f"    {x}")
            sys.exit(1)

        cat = to_tistory_category(pipeline.map_blog_category(prod))
        print(f"본문 {len(post['content'])}자 · 업로드할 이미지 {len(img_paths)}장 "
              f"· 카테고리 '{cat}'")

        # 상품별 검색 키워드를 태그로 쓴다(전에는 모든 글에 같은 태그 3개가 박혔다)
        import keyword_finder
        try:
            tags = keyword_finder.keyword_string(prod, n=10)
            print(f"검색 키워드 {len(tags.split(','))}개: {tags[:70]}")
        except Exception as e:
            print(f"키워드 조회 실패, 상품명 사용: {str(e)[:50]}")
            tags = prod.get("title", "")[:20]

        res = write_post(pipeline.ad_title(post["title"]), html,
                         tags=tags,
                         affiliate_url="", mode=mode, prebuilt_html=True,
                         category=cat, upload_paths=img_paths)
        if res.get("ok"):
            pipeline.record_published(pid, "tistory", res.get("url", ""))
        print("\n결과:", {k: v for k, v in res.items() if k != "layer"})

    elif cmd == "status":
        st = session_status()          # 실제로 편집기까지 들어가 본다
        print(f"세션 상태: {'정상' if st['ok'] else '만료'} · 쿠키 잔여 약 {st['days']}일")
        print(f"  {st['why']}")

    elif cmd == "keepalive":
        keepalive()

    elif cmd == "login":
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            ctx = _ctx(pw)
            ok = ensure_login(_page(ctx), wait_minutes=8)
            print("로그인 세션:", "저장됨" if ok else "실패")
            ctx.close()
    else:
        print(__doc__)
