# ============================================================
#  login.py — 채널 로그인 세션 만들기/점검  (사무실 PC에서 실행)
#
#  ⚠ 이 스크립트는 비밀번호를 묻지도, 저장하지도, 입력하지도 않는다.
#    브라우저 창이 열리면 사장님이 직접 로그인하고, 스크립트는
#    "로그인됐는지"만 확인해서 쿠키(세션)를 저장한다.
#    → .env 나 코드 어디에도 비밀번호가 남지 않는다.
#
#  사용법
#    python login.py --check                     저장된 세션이 아직 살아있는지 점검
#    python login.py band     --account naver_내아이디
#    python login.py facebook --account 내이메일@example.com
#    python login.py kakao                        (로그인 불필요 — 안내만)
#
#  쿠키 저장 위치: 페이스북-광고글/data/cookies/
# ============================================================
import sys
import io
import time
import argparse
from pathlib import Path

import config

COOKIES_DIR = Path(config.FB_PROJECT_APP_DIR).parent / "data" / "cookies"


def _load_automator(platform: str, account: str):
    """실발행 엔진을 지연 import (selenium 은 여기서만 필요).

    ⚠ 엔진은 `from app.paths import ...` 처럼 자기 프로그램의 app 패키지를 쓴다.
      그런데 AutoAd 에도 app.py 가 있어서, 그냥 sys.path 에 넣고 import 하면
      엔진이 AutoAd 의 app.py 를 집어 ImportError 로 죽는다(실측).
      channels.engine 이 import 하는 동안만 app 이름을 격리해 준다."""
    from channels import engine
    if platform == "band":
        mod = engine.load(config.BAND_PROJECT_APP_DIR, "band_automator")
        return mod.BandAutomator(account, headless=False)
    if platform == "facebook":
        mod = engine.load(config.FB_PROJECT_APP_DIR, "facebook_automator")
        return mod.FacebookAutomator(account, headless=False)
    raise ValueError(f"지원하지 않는 채널: {platform}")


def cookie_file(platform: str, account: str) -> Path:
    """엔진이 실제로 쓰는 쿠키 파일 경로.

    ⚠ 규칙은 config.cookie_path 한 곳에만 둔다. 여기서 따로 조합하면
      화면에는 없는 파일명이 찍혀(예: facebook_*.json) 세션을 엉뚱한 데서
      찾게 된다. 실제 파일은 fb_*.json 이다."""
    return config.cookie_path(platform, account)


# ── 세션 점검 (브라우저를 열어 실제로 확인) ─────────────────
def check(platform: str, account: str) -> bool:
    auto = _load_automator(platform, account)
    try:
        auto.driver = auto._create_driver()
        auto._load_cookies()
        auto.driver.get("https://www.band.us/home" if platform == "band"
                        else "https://www.facebook.com")
        time.sleep(3)
        ok = auto._is_logged_in()
        print(f"  [{platform}] {account}: {'세션 살아있음 ✔' if ok else '만료됨 — 재로그인 필요'}")
        return ok
    finally:
        auto.quit()


def check_all():
    """저장된 쿠키 파일을 훑어 어떤 계정이 있는지 먼저 보여준다.

    ⚠ 밴드와 페북은 **서로 다른 프로그램의** data/cookies 를 쓴다.
      예전엔 페북 폴더 하나만 훑고 전부 [band/naver] 로 찍어서,
      실제로는 없는 밴드 세션이 있는 것처럼 보였다(fb_* 파일을 밴드로 오인).
    """
    total = 0
    for platform, app_dir in (("band", config.BAND_PROJECT_APP_DIR),
                              ("facebook", config.FB_PROJECT_APP_DIR)):
        d = Path(app_dir).parent / "data" / "cookies"
        # 파일명 규칙으로 그 플랫폼 것만 고른다(fb_* 는 페북, 나머지는 밴드).
        files = [f for f in sorted(d.glob("*.json"))
                 if (f.name.startswith("fb_")) == (platform == "facebook")]
        print(f"\n[{platform}] {d}")
        if not files:
            print("  (저장된 세션 없음)")
            continue
        for f in files:
            age_d = (time.time() - f.stat().st_mtime) / 86400
            acct = f.stem[len("fb_"):] if f.name.startswith("fb_") else f.stem
            warn = "  ⚠ 오래됨(만료 가능성)" if age_d > 14 else ""
            print(f"  · {acct:34s} {age_d:5.0f}일 전{warn}")
            total += 1
    print(f"\n저장된 세션 {total}개")
    print("실제 유효한지 확인하려면 브라우저가 열립니다:")
    print("  python login.py band --account <아이디> --verify-only")


# ── 수동 로그인 → 쿠키 저장 ─────────────────────────────────
def interactive_login(platform: str, account: str, wait_min: int = 5) -> bool:
    auto = _load_automator(platform, account)
    home = "https://www.band.us/home" if platform == "band" else "https://www.facebook.com"
    try:
        auto.driver = auto._create_driver()

        # 1) 기존 쿠키로 이미 되는지 먼저 시도 (비밀번호 필요 없음)
        auto._load_cookies()
        auto.driver.get(home)
        time.sleep(3)
        if auto._is_logged_in():
            auto._save_cookies()
            print(f"  이미 로그인돼 있습니다 — 세션 갱신 완료 ({cookie_file(platform, account).name})")
            return True

        # 2) 사장님이 직접 로그인
        auto.driver.get("https://auth.band.us/email_login" if platform == "band"
                        else "https://www.facebook.com/login")
        print()
        print("  " + "=" * 60)
        print("  브라우저 창이 열렸습니다. 그 창에서 직접 로그인해 주세요.")
        print("  (이 프로그램은 비밀번호를 묻지도 저장하지도 않습니다)")
        print("  2단계 인증·캡차가 나오면 그것도 창에서 직접 통과하세요.")
        print(f"  로그인되면 자동으로 감지합니다. 최대 {wait_min}분 대기합니다.")
        print("  " + "=" * 60)
        print()

        deadline = time.time() + wait_min * 60
        while time.time() < deadline:
            try:
                if auto._is_logged_in():
                    auto._save_cookies()
                    print(f"\n  로그인 확인 — 세션 저장 완료: {cookie_file(platform, account).name}")
                    print("  이제 다음부터는 비밀번호 없이 자동으로 이 세션을 씁니다.")
                    return True
            except Exception:
                pass
            left = int(deadline - time.time())
            print(f"\r  대기 중... {left // 60}분 {left % 60:02d}초", end="", flush=True)
            time.sleep(3)

        print("\n  시간 초과 — 로그인이 확인되지 않았습니다.")
        return False
    finally:
        auto.quit()


def kakao_notice():
    print("카카오톡은 별도 로그인이 필요 없습니다.")
    print("  · PC 카카오톡을 실행해 로그인된 상태로 열어두기만 하면 됩니다.")
    print("  · AutoHotkey 가 그 창을 조작해 전송합니다.")
    print("  · 전송 중에는 다른 창으로 포커스를 뺏기지 마세요(오전송 위험).")
    try:
        from channels.kakao import KakaoAdapter
        exe = KakaoAdapter()._ahk_exe()
        print(f"  · AutoHotkey: {exe or '미설치 — autohotkey.com 에서 설치 필요'}")
    except Exception:
        pass


def main():
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    except Exception:
        pass

    ap = argparse.ArgumentParser(description="채널 로그인 세션 만들기/점검")
    ap.add_argument("platform", nargs="?", choices=["band", "facebook", "kakao"])
    ap.add_argument("--account", help="밴드=네이버아이디(또는 naver_아이디) / 페북=이메일")
    ap.add_argument("--check", action="store_true", help="저장된 세션 목록 보기")
    ap.add_argument("--verify-only", action="store_true", help="브라우저로 세션 유효성만 확인")
    ap.add_argument("--wait", type=int, default=5, help="로그인 대기 시간(분)")
    a = ap.parse_args()

    if a.check or not a.platform:
        check_all()
        return
    if a.platform == "kakao":
        kakao_notice()
        return
    if not a.account:
        print("--account 를 지정하세요. 예: python login.py band --account naver_myid")
        return

    if a.verify_only:
        check(a.platform, a.account)
    else:
        interactive_login(a.platform, a.account, a.wait)


if __name__ == "__main__":
    main()
