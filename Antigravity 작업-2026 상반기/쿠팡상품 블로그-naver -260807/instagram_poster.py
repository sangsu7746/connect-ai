"""
인스타그램 릴스 업로드. 브라우저를 직접 몬다.

## 왜 Graph API 가 아닌가
공식 경로(Instagram Graph API의 content publishing)는 이 계정 구성으로는 못 쓴다.
프로 계정(비즈니스/크리에이터)으로 전환하고, 페이스북 페이지에 연결하고, 메타 앱을 만들어
`instagram_content_publish` 권한으로 앱 심사를 통과해야 한다. 심사에는 실제 사용 화면
녹화가 필요하고 수 주가 걸린다. 그 전까지는 API 로 한 건도 못 올린다.
게다가 API 는 영상을 공개 URL 로 먼저 올려 둬야 한다 — 이 PC 에는 그런 호스팅이 없다.
그래서 네이버·티스토리와 같은 방식으로 간다. 사람이 로그인하고, 나머지를 자동으로 한다.

## 로그인
**비밀번호는 이 스크립트가 다루지 않는다.** 창이 열리면 사람이 직접 로그인한다.
프로필 디렉터리에 세션을 남겨 두므로 다음 실행부터는 대개 그냥 통과한다.

## 자동화 감지
인스타는 자동화에 민감하다. 한 번에 몰아 올리지 말고 간격을 둔다(UPLOAD_GAP).
계정이 잠기면 이 스크립트로는 풀 수 없다 — 사람이 앱에서 직접 확인해야 한다.
"""
import io
import os
import sys
import time
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROFILE_DIR = os.path.join(BASE_DIR, ".instagram_profile")
HOME = "https://www.instagram.com/"

#: 업로드 사이 간격(초). 연속 업로드는 자동화로 읽힌다.
UPLOAD_GAP = 90
#: 사람이 로그인할 때까지 기다리는 시간(분)
LOGIN_WAIT_MIN = 12.0


def _log(msg: str) -> None:
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}")


def _wait_login(page, log=_log, minutes: float = LOGIN_WAIT_MIN) -> bool:
    """
    로그인 완료를 기다린다. 쿠키 유무가 아니라 '만들기 버튼이 보이는가'로 판정한다.

    예전에 티스토리에서 쿠키 만료일만 보고 "세션 정상"이라고 보고했다가, 실제로는
    죽은 세션이었던 적이 있다. 화면에서 확인되는 것만 정상으로 친다.
    """
    log("  브라우저에서 인스타그램에 직접 로그인해 주세요. (비밀번호는 이 스크립트가 다루지 않습니다)")
    deadline = time.time() + minutes * 60
    while time.time() < deadline:
        try:
            page.goto(HOME, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            for sel in ('svg[aria-label="새로운 게시물"]', 'svg[aria-label="New post"]',
                        'a[href="#"] >> text=만들기', 'a[href="/explore/"]'):
                if page.locator(sel).count():
                    log("  ✔ 로그인 확인")
                    return True
        except Exception:
            pass
        time.sleep(5)
    log("  ✘ 로그인 대기 시간이 지났습니다.")
    return False


def _open_composer(page, log=_log) -> bool:
    """'만들기' 를 눌러 업로드 창을 연다."""
    for sel in ('svg[aria-label="새로운 게시물"]', 'svg[aria-label="New post"]'):
        loc = page.locator(sel)
        if loc.count():
            loc.first.click()
            page.wait_for_timeout(1500)
            # 사이드바 '만들기' 를 누르면 게시물/릴스 선택이 한 번 더 뜨는 경우가 있다
            for sub in ("게시물", "Post"):
                s = page.locator(f'span:has-text("{sub}")')
                if s.count():
                    try:
                        s.first.click()
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass
                    break
            return True
    log("  ✘ '만들기' 버튼을 찾지 못했습니다.")
    return False


def _click_text(page, texts, timeout_ms=8000) -> bool:
    """여러 표기 중 먼저 보이는 버튼을 누른다(한/영 UI 대응)."""
    end = time.time() + timeout_ms / 1000
    while time.time() < end:
        for t in texts:
            loc = page.locator(f'div[role="button"]:has-text("{t}"), button:has-text("{t}")')
            if loc.count():
                try:
                    loc.last.click()
                    return True
                except Exception:
                    pass
        page.wait_for_timeout(400)
    return False


def _upload_one(page, video_path: str, caption: str, log=_log) -> dict:
    """릴스 한 건 업로드."""
    if not os.path.exists(video_path):
        return {"ok": False, "why": f"영상 파일이 없습니다: {video_path}"}

    if not _open_composer(page, log):
        return {"ok": False, "why": "업로드 창을 열지 못했습니다."}

    # 파일 선택
    try:
        with page.expect_file_chooser(timeout=15000) as fc:
            if not _click_text(page, ["컴퓨터에서 선택", "Select from computer"], 10000):
                return {"ok": False, "why": "'컴퓨터에서 선택' 버튼을 찾지 못했습니다."}
        fc.value.set_files(video_path)
    except Exception as e:
        return {"ok": False, "why": f"파일 선택 실패: {str(e)[:120]}"}

    page.wait_for_timeout(6000)
    # 영상은 업로드 후 인스타가 릴스로 처리하겠다고 물어보는 단계가 끼기도 한다
    _click_text(page, ["확인", "OK"], 3000)

    # 자르기 → 편집 → 세부정보. '다음' 을 두 번 누른다.
    for step in (1, 2):
        if not _click_text(page, ["다음", "Next"], 25000):
            return {"ok": False, "why": f"'다음' {step}단계에서 멈췄습니다."}
        page.wait_for_timeout(2500)

    # 문구 입력
    try:
        box = page.locator('div[aria-label="문구 입력..."], div[aria-label="Write a caption..."]')
        if not box.count():
            box = page.locator('div[contenteditable="true"]')
        box.first.click()
        page.wait_for_timeout(400)
        # 줄바꿈이 많아 타이핑이 느리다. 붙여넣기로 넣는다.
        page.evaluate("t => navigator.clipboard.writeText(t)", caption)
        page.keyboard.press("Control+V")
        page.wait_for_timeout(1500)
        if not box.first.inner_text().strip():
            box.first.type(caption, delay=8)
            page.wait_for_timeout(1000)
    except Exception as e:
        return {"ok": False, "why": f"문구 입력 실패: {str(e)[:120]}"}

    # 공유
    if not _click_text(page, ["공유하기", "Share"], 15000):
        return {"ok": False, "why": "'공유하기' 버튼을 찾지 못했습니다."}

    # 처리 대기 — 영상은 인코딩 때문에 오래 걸린다
    for _ in range(60):
        page.wait_for_timeout(3000)
        for t in ("게시물을 공유했습니다", "Your post has been shared",
                  "릴스를 공유했습니다", "Your reel has been shared"):
            if page.locator(f'text={t}').count():
                return {"ok": True, "url": ""}
    return {"ok": False, "why": "공유 완료 확인 문구가 뜨지 않았습니다(업로드됐을 수도 있습니다 — 앱에서 확인하세요)."}


def upload_reels(jobs: list, headless: bool = False, log=_log) -> dict:
    """
    jobs: [{"key":..., "video":<mp4 경로>, "caption":<문구>}, ...]
    한 세션에서 전부 처리한다.
    """
    from playwright.sync_api import sync_playwright

    results = {}
    os.makedirs(PROFILE_DIR, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            PROFILE_DIR,
            headless=headless,
            locale="ko-KR",
            viewport={"width": 1280, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        try:
            ctx.grant_permissions(["clipboard-read", "clipboard-write"],
                                  origin="https://www.instagram.com")
        except Exception:
            pass
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        if not _wait_login(page, log):
            for j in jobs:
                results[j["key"]] = {"ok": False, "why": "로그인하지 못했습니다."}
            ctx.close()
            return results

        for i, j in enumerate(jobs):
            log(f"  [{i+1}/{len(jobs)}] 업로드: {os.path.basename(j['video'])}")
            try:
                results[j["key"]] = _upload_one(page, j["video"], j["caption"], log)
            except Exception as e:
                results[j["key"]] = {"ok": False, "why": str(e)[:150]}
            r = results[j["key"]]
            log(("    ✅ 완료" if r.get("ok") else f"    ✘ {r.get('why')}"))

            if i < len(jobs) - 1:
                log(f"    {UPLOAD_GAP}초 쉬고 다음 건으로 갑니다(연속 업로드는 자동화로 읽힙니다).")
                time.sleep(UPLOAD_GAP)
                try:
                    page.goto(HOME, wait_until="domcontentloaded", timeout=30000)
                    page.wait_for_timeout(2000)
                except Exception:
                    pass

        ctx.close()
    return results


if __name__ == "__main__":
    print(__doc__)
