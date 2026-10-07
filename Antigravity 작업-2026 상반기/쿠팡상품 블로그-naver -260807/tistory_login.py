# -*- coding: utf-8 -*-
"""티스토리(카카오) 로그인 창을 띄우기만 한다. 비밀번호는 사람이 직접 입력한다.

naver_login.py 와 같은 원칙 — 창을 붙들지 않는다.
파이썬이 브라우저를 쥐고 기다리면 제한 시간에 쫓기고, 사람이 창을 닫으면 스크립트가 깨진다.
띄우고 바로 빠진다. 확인은 나중에 따로:

    python tistory_login.py            ← 창을 띄운다 (바로 끝남)
    ... 사람이 로그인하고 창을 닫는다 ...
    python -c "import tistory_poster as t;print(t.session_status())"

주의: 확인하려면 **창을 닫아야 한다.** 크롬이 프로필을 잠그고 있으면 접속할 수 없다.
"""
import glob
import json
import os
import subprocess

BASE = os.path.dirname(os.path.abspath(__file__))
PROFILE = os.path.join(BASE, ".tistory_profile")

try:
    from tistory_poster import NEWPOST_URL
except Exception:
    NEWPOST_URL = "https://www.tistory.com/"


def chromium_path() -> str:
    """확인에 쓰는 Playwright 크로미움을 그대로 쓴다 (쿠키 호환)."""
    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright")
    found = sorted(glob.glob(os.path.join(root, "chromium-*", "chrome-win*", "chrome.exe")))
    if found:
        return found[-1]
    for p in (
        os.path.join(os.environ.get("ProgramFiles", ""), "Google", "Chrome", "Application", "chrome.exe"),
        os.path.join(os.environ.get("ProgramFiles(x86)", ""), "Google", "Chrome", "Application", "chrome.exe"),
    ):
        if os.path.exists(p):
            return p
    return ""


def main():
    os.makedirs(PROFILE, exist_ok=True)
    exe = chromium_path()
    if not exe:
        print(json.dumps({"ok": False, "error": "브라우저를 찾지 못했습니다"}, ensure_ascii=False))
        return

    subprocess.Popen(
        [
            exe,
            f"--user-data-dir={PROFILE}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-blink-features=AutomationControlled",
            "--lang=ko-KR",
            NEWPOST_URL,
        ],
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )
    print(json.dumps({
        "ok": True,
        "profile": os.path.basename(PROFILE),
        "url": NEWPOST_URL,
        "note": "창이 열렸습니다. 카카오 계정으로 로그인한 뒤 창을 닫아주세요.",
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
