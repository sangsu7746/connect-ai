# -*- coding: utf-8 -*-
"""네이버 블로그 로그인 창을 띄우기만 한다. 비밀번호는 사람이 직접 입력한다.

이 스크립트는 아이디·비밀번호를 저장하지도, 입력하지도, 읽지도 않는다.

**창을 붙들지 않는다.** 예전 방식은 파이썬이 브라우저를 쥐고 기다렸는데,
그러면 (1) 제한 시간에 쫓기고 (2) 사람이 창을 닫으면 스크립트가 깨졌다.
지금은 브라우저를 띄우고 바로 빠진다. 사장님이 원하는 만큼 쓰고 그냥 닫으면 된다.
쿠키는 프로필 폴더에 남으므로 확인은 나중에 따로 한다:

    python naver_login.py headjim     ← 창을 띄운다 (바로 끝남)
    ... 사람이 로그인 ...
    python naver_keepalive.py headjim ← 됐는지 확인한다

블로그마다 전용 프로필을 쓴다 — 네이버는 계정 1개당 블로그 1개라,
프로필을 같이 쓰면 나중에 로그인한 계정이 앞의 것을 덮어쓴다.
"""
import glob
import json
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
WRITE_URL = "https://blog.naver.com/{blog_id}/postwrite"


def chromium_path() -> str:
    """Playwright 가 쓰는 크로미움을 그대로 쓴다.

    확인은 Playwright 로 하므로 프로필을 만든 브라우저와 읽는 브라우저가 같아야
    쿠키 호환 문제가 안 생긴다. 없으면 시스템 크롬으로 넘어간다.
    """
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    found = sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-win*", "chrome.exe")))
    if found:
        return found[-1]  # 가장 최신 빌드
    for p in (
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ):
        if os.path.exists(p):
            return p
    return ""


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"ok": False, "error": "blogId 를 주세요 (예: python naver_login.py headjim)"},
                         ensure_ascii=False))
        return
    blog_id = sys.argv[1].strip()
    prof = os.path.join(BASE, f".naver_profile_{blog_id}")
    os.makedirs(prof, exist_ok=True)

    exe = chromium_path()
    if not exe:
        print(json.dumps({"ok": False, "error": "브라우저를 찾지 못했습니다"}, ensure_ascii=False))
        return

    # 띄우고 바로 빠진다. 창의 수명은 사람이 정한다.
    subprocess.Popen(
        [
            exe,
            f"--user-data-dir={prof}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--lang=ko-KR",
            WRITE_URL.format(blog_id=blog_id),
        ],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )

    print(json.dumps({
        "ok": True,
        "blog": blog_id,
        "profile": os.path.basename(prof),
        "note": "창이 열렸습니다. 로그인 후 창을 닫으셔도 됩니다. 확인은 naver_keepalive.py 로 합니다.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
