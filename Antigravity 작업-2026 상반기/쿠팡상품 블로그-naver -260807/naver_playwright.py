# -*- coding: utf-8 -*-
"""네이버 블로그 발행 — Playwright 판.

왜 새로 만들었나 (2026-08-25):
  기존 naver_poster.py 는 Selenium 이라 **OS 파일 선택 창을 다루지 못한다.**
  네이버 스마트에디터에는 `input[type=file]` 이 없고(실측 TimeoutException 6/6),
  사진 버튼을 누르면 OS 창이 뜬다. Selenium 은 그걸 잡을 수 없어 pyautogui 로
  마우스·키보드를 흉내냈는데, 창 포커스가 어긋나면 **본문이 통째로 날아가고
  로컬 경로가 공개되는 사고**가 났다(실제 발생).

  Playwright 는 `expect_file_chooser` 로 그 창을 직접 가로챈다. 티스토리에서
  같은 방식으로 이미지 6/6 을 올려 검증했다. 마우스·키보드도 뺏지 않는다.

로그인은 기존 자산을 그대로 쓴다 — Selenium 이 저장해 둔 쿠키(pickle)를
Playwright 컨텍스트로 옮긴다. 비밀번호는 이 코드가 다루지 않는다.
"""
import json
import os
import pickle
import re
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROFILE_DIR = os.path.join(BASE_DIR, ".naver_profile")
WRITE_URL = "https://blog.naver.com/{blog_id}/postwrite"


def _cookie_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".naver_poster_cookies.pkl")


def _load_selenium_cookies() -> list:
    """Selenium 이 저장한 쿠키를 Playwright 형식으로 바꾼다."""
    p = _cookie_path()
    if not os.path.exists(p):
        return []
    try:
        with open(p, "rb") as f:
            raw = pickle.load(f)
    except Exception:
        return []
    out = []
    for c in raw:
        ck = {
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain") or ".naver.com",
            "path": c.get("path") or "/",
        }
        if not ck["name"] or ck["value"] is None:
            continue
        if c.get("expiry"):
            ck["expires"] = float(c["expiry"])
        # Selenium 의 sameSite 값이 Playwright 와 표기가 다르다
        ss = (c.get("sameSite") or "").capitalize()
        ck["sameSite"] = ss if ss in ("Strict", "Lax", "None") else "Lax"
        ck["secure"] = bool(c.get("secure"))
        ck["httpOnly"] = bool(c.get("httpOnly"))
        out.append(ck)
    return out


def md_to_plain(md: str) -> str:
    """마크다운 기호만 걷어낸다. 에디터가 HTML 을 해석하지 않고 타이핑만 받기 때문."""
    lines = []
    for raw in (md or "").split("\n"):
        s = raw.strip()
        s = re.sub(r"^#{1,6}\s+", "", s)
        s = re.sub(r"^[-*•]\s+", "· ", s)
        s = re.sub(r"\*\*(.+?)\*\*", r"\1", s)
        s = re.sub(r"(?<!\*)\*([^*]+?)\*(?!\*)", r"\1", s)
        lines.append(s)
    return "\n".join(lines)


def _split_sections(md: str) -> list:
    """소제목(## )을 경계로 본문을 구간으로 나눈다.

    구간마다 이미지를 하나씩 끼우기 위한 것이다. 본문을 통째로 친 뒤 이미지를 넣으면
    커서가 글 맨 끝에 있어 그림이 전부 아래에 쌓인다(실측).
    """
    plain_blocks = []
    cur = []
    for raw in (md or "").split("\n"):
        if re.match(r"^#{1,6}\s+", raw.strip()) and cur:
            plain_blocks.append("\n".join(cur).strip())
            cur = [raw]
        else:
            cur.append(raw)
    if cur:
        plain_blocks.append("\n".join(cur).strip())
    return [md_to_plain(b) for b in plain_blocks if b.strip()]


class NaverBlog:
    def __init__(self, blog_id: str, headless: bool = False, log=print):
        self.blog_id = blog_id
        self.headless = headless
        self.log = log
        self._pw = None
        self.ctx = None
        self.page = None

    def profile_dir(self) -> str:
        """블로그마다 다른 네이버 계정일 수 있다.

        네이버는 계정 1개당 블로그 1개다. 그래서 블로그가 여러 개면 계정도 여러 개이고,
        프로필(쿠키 저장소)을 같이 쓰면 나중에 로그인한 계정이 앞의 것을 덮어쓴다.
        `.naver_profile_<blogId>` 가 있으면 그걸 쓰고, 없으면 기존 단일 프로필을 쓴다
        (계정이 하나뿐이던 시절과 호환).
        """
        special = os.path.join(BASE_DIR, f".naver_profile_{self.blog_id}")
        return special if os.path.isdir(special) else PROFILE_DIR

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        prof = self.profile_dir()
        os.makedirs(prof, exist_ok=True)
        self.ctx = self._pw.chromium.launch_persistent_context(
            prof,
            headless=self.headless,
            locale="ko-KR",
            timezone_id="Asia/Seoul",
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        # 저장된 pickle 쿠키는 **기존 단일 프로필에만** 넣는다.
        # 그 쿠키는 config.json 의 naver_id(apahand) 계정 것이라, 블로그 전용 프로필에 넣으면
        # headjim 창이 apahand 로 로그인돼 버린다 — 글이 엉뚱한 블로그로 간다.
        if prof == PROFILE_DIR:
            cookies = _load_selenium_cookies()
            if cookies:
                try:
                    self.ctx.add_cookies(cookies)
                    self.log(f"  → 저장된 쿠키 {len(cookies)}개 적용")
                except Exception as e:
                    self.log(f"  ⚠️ 쿠키 적용 실패: {str(e)[:60]}")
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("dialog", lambda d: d.accept())
        return self

    def __exit__(self, *a):
        try:
            self.ctx.close()
        except Exception:
            pass
        try:
            self._pw.stop()
        except Exception:
            pass

    # ── 로그인 ────────────────────────────────────────────────
    def ensure_login(self, wait_minutes: float = 10) -> bool:
        """글쓰기 화면에 도달할 때까지. 로그인 화면이면 사람이 직접 하도록 기다린다."""
        p = self.page
        p.goto(WRITE_URL.format(blog_id=self.blog_id), wait_until="domcontentloaded", timeout=60000)
        p.wait_for_timeout(4000)
        if self._on_editor():
            self.log("  → 편집기 확인 (쿠키 재사용 성공)")
            return True

        self.log("\n" + "=" * 60)
        self.log("  네이버 로그인이 필요합니다.")
        self.log("  ** 지금 열린 창에서 ** 직접 로그인해 주세요.")
        self.log("  비밀번호는 이 코드가 다루지 않습니다.")
        self.log(f"  최대 {wait_minutes:.0f}분 기다립니다...")
        self.log("=" * 60 + "\n")
        deadline = time.time() + wait_minutes * 60
        while time.time() < deadline:
            p.wait_for_timeout(3000)
            if self._on_editor():
                self.log("  → 편집기 도달")
                return True
            if "nid.naver.com" not in p.url and "postwrite" not in p.url:
                try:
                    p.goto(WRITE_URL.format(blog_id=self.blog_id),
                           wait_until="domcontentloaded", timeout=45000)
                except Exception:
                    pass
        self.log("  시간 초과 — 편집기에 도달하지 못했습니다.")
        return False

    def _frame(self):
        """에디터가 mainFrame 안에 있을 수도, 바로 노출될 수도 있다."""
        for f in self.page.frames:
            if f.name == "mainFrame":
                return f
        return self.page

    def _on_editor(self) -> bool:
        try:
            return self._frame().locator(".se-title-text, .se-title-input, #title").count() > 0
        except Exception:
            return False

    # ── 작성 ──────────────────────────────────────────────────
    def write(self, title: str, body_md: str, images=None, tags=None) -> dict:
        fr = self._frame()
        out = {"uploaded": 0}

        # 처음 뜨는 '이전 글 이어쓰기' 같은 팝업을 닫는다
        for sel in ["button:has-text('취소')", ".se-popup-button-cancel", "button:has-text('닫기')"]:
            try:
                el = fr.locator(sel).first
                if el.count() and el.is_visible():
                    el.click(timeout=3000)
                    self.page.wait_for_timeout(800)
            except Exception:
                pass

        self.log("📌 제목 입력…")
        fr.locator(".se-title-text, .se-title-input, #title").first.click(timeout=15000)
        self.page.wait_for_timeout(600)
        self.page.keyboard.type(title, delay=25)
        self.page.wait_for_timeout(600)

        # 본문 영역으로 옮긴다. Tab 만 믿으면 포커스가 안 넘어가 본문 첫 줄이 제목에 이어 붙는다
        # (실측: 제목이 75자가 되어 소제목까지 제목에 들어갔다). 본문 영역을 직접 클릭한다.
        self.page.keyboard.press("Tab")
        self.page.wait_for_timeout(500)
        try:
            fr.locator(".se-component.se-text .se-text-paragraph, .se-content").first.click(timeout=8000)
            self.page.wait_for_timeout(500)
        except Exception:
            pass

        # 본문과 이미지를 번갈아 넣는다.
        # 본문을 다 친 뒤 이미지를 몰아 넣으면 커서가 글 끝에 있어서 이미지가 전부 맨 아래 쌓인다.
        # 소제목 단위로 끊어 치고 그 자리에서 한 장씩 넣어야 단락마다 그림이 들어간다.
        blocks = _split_sections(body_md)
        pool = list(images or [])
        out["uploaded"] = 0
        self.log(f"📄 본문 {len(blocks)}구간 · 이미지 {len(pool)}장 — 번갈아 입력")

        # 표지는 글 맨 위에 (대표 이미지가 된다)
        if pool:
            if self._insert_image(fr, pool.pop(0)):
                out["uploaded"] += 1
                self.log("  → 표지 이미지")

        for bi, block in enumerate(blocks, 1):
            self.page.keyboard.type(block, delay=3)
            self.page.keyboard.press("Enter")
            self.page.wait_for_timeout(500)
            self.log(f"  → 구간 {bi} ({len(block)}자)")
            # 마지막 구간 뒤에는 넣지 않는다 — 남은 것은 아래에서 처리
            if pool and bi < len(blocks):
                if self._insert_image(fr, pool.pop(0)):
                    out["uploaded"] += 1
                    self.log(f"     이미지 {out['uploaded']}장")

        # 구간보다 이미지가 많으면 남은 것은 글 끝에 붙인다
        for img in pool:
            if self._insert_image(fr, img):
                out["uploaded"] += 1
        if images:
            self.log(f"📸 {out['uploaded']}/{len(images)}장 반영됨 (에디터 확인 기준)")
            self.page.wait_for_timeout(3000)

        # ── 이미지 ────────────────────────────────────────────
        # 사진 버튼을 누르면 input#hidden-file 이 파일 선택 창을 띄운다. 그걸 가로챈다.
        #
        # 중요 — 파일을 건넸다고 끝이 아니다. 업로드가 에디터에 반영되기까지 몇 초 걸리고,
        # 반영 전에 발행을 누르면 그 이미지는 빠진 채로 올라간다(실측: 6/6 '첨부' 로그에도
        # 발행된 글은 0장이었다). 그래서 **에디터에 실제로 늘어난 것을 확인하고** 다음으로 간다.
        # ── 발행 ──────────────────────────────────────────────
        # 2단계다: 상단 '발행'(publish_btn) → 설정 레이어 → 레이어의 '발행'(confirm_btn).
        # 글자만 보고 고르면 안 된다 — '발행' 이라는 글자를 가진 요소가 여러 개이고,
        # 툴바 버튼들이 뒤에 더 있어서 '마지막 것'을 누르면 엉뚱한 걸 누른다(실제로 그래서 실패했다).
        # 네이버가 쓰는 클래스 접두사로 정확히 집는다.
        self.log("🚀 발행 설정 열기…")
        self.page.wait_for_timeout(1000)
        if not self._click_any(["button[class*='publish_btn__']",
                                "[class*='publish_btn_area__'] button",
                                "button:has-text('발행')"]):
            self.log("  ⚠️ 발행 버튼을 찾지 못했습니다")
            return {**out, "url": "", "error": "발행 버튼 없음"}
        self.page.wait_for_timeout(2500)

        if tags:
            self.log(f"🏷️ 태그: {', '.join(tags)}")
            for t in tags[:10]:
                try:
                    ti = self.page.locator(
                        "input[placeholder*='태그 입력'], textarea[placeholder*='태그 입력'],"
                        " .tag_input input, [class*=tagInput] input").first
                    ti.click(timeout=8000)
                    self.page.keyboard.type(t, delay=40)
                    self.page.keyboard.press("Enter")
                    self.page.wait_for_timeout(400)
                except Exception:
                    break

        self.page.wait_for_timeout(800)
        self.log("🚀 최종 발행…")
        if not self._click_any(["button[class*='confirm_btn__']",
                                "[class*='layer_btn_area__'] button:has-text('발행')",
                                ".btn_confirm"]):
            self.log("  ⚠️ 최종 발행 버튼을 찾지 못했습니다")
            return {**out, "url": "", "error": "최종 발행 버튼 없음"}

        # 발행되면 글 주소로 이동한다. 그걸 성공 판정으로 쓴다 — 버튼을 눌렀다는 것만으로는
        # 올라갔는지 알 수 없다(예전에 '완료' 로그만 찍고 실제로는 안 올라간 적이 있다).
        try:
            self.page.wait_for_url(re.compile(r"/\d{9,}"), timeout=30000)
        except Exception:
            self.page.wait_for_timeout(5000)
        out["url"] = self._published_url()
        if out["url"]:
            self.log(f"🎉 발행 완료 {out['url']}")
        else:
            out["error"] = "발행 확인 실패 — 글 주소로 이동하지 않았습니다"
            self.log(f"  ⚠️ {out['error']} (현재 주소: {self.page.url[:60]})")
        return out

    _IMG_COUNT_JS = ("() => document.querySelectorAll("
                     "'.se-component.se-image, .se-image-resource, .se-section-image').length")

    def _editor_image_count(self) -> int:
        try:
            return int(self.page.evaluate(self._IMG_COUNT_JS))
        except Exception:
            return 0

    def _insert_image(self, fr, img_path: str) -> bool:
        """지금 커서 자리에 이미지 한 장을 넣고, 에디터에 실제로 반영될 때까지 기다린다."""
        try:
            before = self._editor_image_count()
            btn = fr.locator("button[data-name='image'], button.se-image-toolbar-button,"
                             " button[title*='사진'], button[aria-label*='사진']").first
            with self.page.expect_file_chooser(timeout=15000) as fc:
                btn.click(timeout=10000)
            fc.value.set_files(img_path)
            if not self._wait_image_added(before, timeout_s=40):
                self.log("     ⚠️ 이미지가 에디터에 반영되지 않았습니다")
                return False
            # 이미지 뒤에 커서를 두어 다음 글이 그림 아래로 이어지게 한다
            self.page.keyboard.press("End")
            self.page.wait_for_timeout(400)
            return True
        except Exception as e:
            self.log(f"     ⚠️ 이미지 첨부 실패: {type(e).__name__}")
            return False

    def _wait_image_added(self, before: int, timeout_s: float = 40) -> bool:
        """에디터에 이미지가 실제로 늘어날 때까지 기다린다.

        업로드는 blog.upphoto.naver.com 으로 나가고 반영까지 3초 남짓 걸린다(실측).
        이 확인 없이 다음으로 넘어가면 발행 시 이미지가 빠진다.
        """
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            self.page.wait_for_timeout(1000)
            if self._editor_image_count() > before:
                return True
        return False

    def _click_any(self, selectors, last=False):
        for sel in selectors:
            try:
                loc = self.page.locator(sel)
                n = loc.count()
                if not n:
                    continue
                el = loc.nth(n - 1) if last else loc.first
                if el.is_visible():
                    el.click(timeout=8000)
                    return True
            except Exception:
                continue
        return False

    def _published_url(self) -> str:
        """발행된 글 주소를 구한다.

        발행 후 주소는 두 가지로 온다 — `/blogId/224…` 또는
        `PostView.naver?blogId=…&logNo=224…&Redirect=…`. 앞의 형태만 보면 성공인데도
        실패로 판정한다(실측). 두 가지 다 받고, 그래도 안 되면 목록에서 최신 글을 확인한다.
        """
        u = self.page.url
        m = re.search(r"logNo=(\d{9,})", u) or re.search(r"/(\d{9,})", u)
        if m:
            return f"https://blog.naver.com/{self.blog_id}/{m.group(1)}"
        # 주소로 못 구했으면 목록에서 확인한다 — 버튼을 눌렀다는 것만으로 성공이라 하지 않는다
        try:
            r = self.page.request.get(
                "https://blog.naver.com/PostTitleListAsync.naver"
                f"?blogId={self.blog_id}&currentPage=1&countPerPage=1"
            )
            m2 = re.search(r'"logNo":"?(\d{9,})', r.text())
            if m2:
                return f"https://blog.naver.com/{self.blog_id}/{m2.group(1)}"
        except Exception:
            pass
        return ""


def _handoff_path() -> str:
    """인자를 두 가지 형태로 받는다.

    `--file <경로>`  : 카드뉴스 서버가 부르는 방식 (publish_generic.py 와 동일)
    `<경로>`        : 사람이 직접 돌릴 때
    예전에는 위치 인자만 읽어서, 서버가 `--file` 로 부르면 '--file' 을 파일 이름으로
    열려다 FileNotFoundError 로 죽었다.
    """
    args = sys.argv[1:]
    if "--file" in args:
        i = args.index("--file")
        if i + 1 < len(args):
            return args[i + 1]
        raise SystemExit("--file 뒤에 경로가 없습니다")
    if args:
        return args[0]
    raise SystemExit("handoff json 경로가 필요합니다 (--file <경로>)")


def main():
    h = json.load(open(_handoff_path(), encoding="utf-8"))
    blog_id = h.get("blog_id") or ""
    if not blog_id:
        print(json.dumps({"ok": False, "error": "blog_id 가 없습니다"}, ensure_ascii=False))
        return
    logs = []

    def log(m):
        print(m)
        logs.append(str(m))

    with NaverBlog(blog_id, log=log) as nb:
        if not nb.ensure_login(float(h.get("wait_minutes", 10))):
            print(json.dumps({"ok": False, "error": "로그인 실패", "logs": logs}, ensure_ascii=False))
            return
        r = nb.write(h["title"], h["body_md"], h.get("images") or [], h.get("tags") or [])
        print(json.dumps({"ok": bool(r.get("url")), **r, "logs": logs}, ensure_ascii=False))


if __name__ == "__main__":
    main()
