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
#: 사람이 로그인할 때까지 기다리는 시간(분).
#: 인스타는 2단계 인증·기기 확인 메일을 요구할 때가 있어 넉넉해야 한다.
LOGIN_WAIT_MIN = 30.0


def _release_profile_lock(log=None) -> int:
    """
    앞선 실행이 남긴 크로미움을 정리한다.

    persistent context 는 프로필 디렉터리를 한 프로세스만 쓸 수 있다. 앞 실행이
    비정상 종료하면 크로미움이 살아남아 잠금을 쥐고, 다음 실행은 시작하자마자
    "프로필이 이미 사용 중"으로 죽는다 — 실제로 그렇게 한 번 날렸다.
    """
    import re
    import subprocess

    killed = 0
    try:
        out = subprocess.run(
            ["wmic", "process", "where", "name='chrome.exe'",
             "get", "processid,commandline", "/format:csv"],
            capture_output=True).stdout.decode("utf-8", "replace")
        for line in out.splitlines():
            if os.path.basename(PROFILE_DIR) not in line:
                continue
            m = re.search(r"(\d+)\s*$", line.strip())
            if m:
                subprocess.run(["taskkill", "/PID", m.group(1), "/T", "/F"],
                               capture_output=True)
                killed += 1
    except Exception:
        pass

    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
        try:
            os.remove(os.path.join(PROFILE_DIR, name))
        except Exception:
            pass

    if killed and log:
        log(f"  이전 실행이 남긴 브라우저 {killed}개를 정리했습니다.")
    return killed


def _log(msg: str) -> None:
    # flush 를 안 하면 파일로 리다이렉트했을 때 진행 상황이 한참 뒤에야 보인다.
    # 로그인 대기처럼 '지금 뭘 기다리는지'가 중요한 단계에서 치명적이다.
    print(f"[{datetime.now():%m-%d %H:%M:%S}] {msg}", flush=True)


def _wait_login(page, log=_log, minutes: float = LOGIN_WAIT_MIN) -> bool:
    """
    로그인 완료를 기다린다. 쿠키 유무가 아니라 '만들기 버튼이 보이는가'로 판정한다.

    예전에 티스토리에서 쿠키 만료일만 보고 "세션 정상"이라고 보고했다가, 실제로는
    죽은 세션이었던 적이 있다. 화면에서 확인되는 것만 정상으로 친다.
    """
    log("  브라우저에서 인스타그램에 직접 로그인해 주세요. (비밀번호는 이 스크립트가 다루지 않습니다)")
    log(f"  {minutes:.0f}분 기다립니다. 천천히 하셔도 됩니다 — 화면은 건드리지 않습니다.")

    # 처음 한 번만 연다.
    #
    # 예전에는 이 루프가 5초마다 page.goto(HOME) 을 다시 걸었다. 그러면 아이디를
    # 입력하는 중에 페이지가 새로 열려 입력한 것이 날아간다. 로그인 자체가 불가능했다.
    # 로그인 여부는 화면을 다시 여는 것이 아니라 지금 떠 있는 DOM 을 보고 판단한다.
    try:
        page.goto(HOME, wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass

    MARKS = ('svg[aria-label="새로운 게시물"]', 'svg[aria-label="New post"]',
             'a[href="/explore/"]', 'svg[aria-label="홈"]', 'svg[aria-label="Home"]')

    deadline = time.time() + minutes * 60
    notified = 0
    while time.time() < deadline:
        try:
            for sel in MARKS:
                if page.locator(sel).count():
                    log("  ✔ 로그인 확인")
                    return True
        except Exception:
            # 사용자가 페이지를 옮기는 중이면 조회가 잠깐 실패한다. 그냥 넘어간다.
            pass

        left = int(deadline - time.time())
        if left // 60 != notified:
            notified = left // 60
            log(f"    로그인 대기 중… {left // 60}분 남음")
        time.sleep(3)

    log("  ✘ 로그인 대기 시간이 지났습니다.")
    return False


def _click_icon(page, labels, wait_ms: int = 3000) -> bool:
    """
    아이콘을 화면 좌표로 누른다.

    svg 를 locator.click() 으로 누르면 부모 div 가 클릭을 가로챈다
    ("subtree intercepts pointer events"). 아이콘을 감싼 a 를 :has() 로 잡아도
    같은 이유로 실패했다. 결국 좌표를 구해 그 자리를 마우스로 누르는 것이 확실하다.
    """
    for label in labels:
        loc = page.locator(f'svg[aria-label="{label}"]')
        if not loc.count():
            continue
        try:
            box = loc.first.bounding_box()
        except Exception:
            continue
        if not box:
            continue
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.wait_for_timeout(wait_ms)
        return True
    return False


def _open_composer(page, log=_log) -> bool:
    """
    '만들기 → 게시물' 로 업로드 창을 연다.

    메뉴에 '릴스' 항목은 없다. 세로 영상을 게시물로 올리면 인스타가 알아서 릴스로 만든다.
    """
    if not _click_icon(page, ("새로운 게시물", "New post", "만들기", "Create")):
        log("  ✘ '만들기' 아이콘을 찾지 못했습니다.")
        return False
    # 만들기를 누르면 '게시물 / 라이브 방송 / 광고' 가 펼쳐진다.
    _click_icon(page, ("게시물", "Post"), wait_ms=4000)
    return True


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

    # 파일 넣기
    #
    # '컴퓨터에서 선택' 을 눌러 파일 대화상자를 받는 방식은 계속 시간 초과가 났다.
    # 인스타는 업로드 창을 열 때 숨겨진 input[type=file] 을 DOM 에 넣어 둔다
    # (accept 에 video/mp4 가 들어 있다). 거기에 파일을 직접 꽂는 편이 확실하다.
    # set_input_files 는 숨겨진 input 에도 동작하고, change 이벤트까지 발생시킨다.
    try:
        inp = page.locator('input[type="file"]')
        page.wait_for_selector('input[type="file"]', state="attached", timeout=20000)
        target = inp.first
        for i in range(inp.count()):
            if "video" in (inp.nth(i).get_attribute("accept") or ""):
                target = inp.nth(i)
                break
        target.set_input_files(video_path)
    except Exception as e:
        return {"ok": False, "why": f"파일 넣기 실패: {str(e)[:120]}"}

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
    _release_profile_lock(log)
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
