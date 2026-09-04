# ============================================================
#  channels/kakao.py — 카카오톡 방 어댑터  (P1-3 확장)
#  엔진: 대출위젯-카카오/kakao_send.ahk (AutoHotkey 데스크톱 자동화)
#  · sender.py 는 대출앱 config('config' 이름충돌) 의존 → import 대신
#    AHK 호출부만 vendoring하고 kakao_send.ahk 를 그대로 재사용.
#  ⚠ AHK/UI자동화는 취약 — 방 이름 검증 필수(오전송 방지) + GLOBAL_DRY_RUN 차단.
# ============================================================
import os
import subprocess
import tempfile
from pathlib import Path

import config
from channels.base import BaseAdapter, PostResult, Feedback

_AHK_CANDIDATES = [
    r"C:\Program Files\AutoHotkey\v2\AutoHotkey64.exe",
    r"C:\Program Files\AutoHotkey\AutoHotkey64.exe",
    r"C:\Program Files (x86)\AutoHotkey\v2\AutoHotkey64.exe",
    r"C:\Program Files\AutoHotkey\AutoHotkeyU64.exe",
    r"C:\Program Files (x86)\AutoHotkey\AutoHotkey.exe",
]


class KakaoAdapter(BaseAdapter):
    platform = "kakao"

    def __init__(self):
        self._ahk = None

    def login(self, cred: dict = None) -> bool:
        # 카카오톡 PC앱은 이미 로그인된 창을 UI자동화로 조작 → 별도 로그인 없음
        return True

    @staticmethod
    def _valid_target(room: str) -> bool:
        return bool(room and str(room).strip())

    def _ahk_exe(self):
        if self._ahk:
            return self._ahk
        for p in _AHK_CANDIDATES:
            if Path(p).exists():
                self._ahk = p
                return p
        for name in ["AutoHotkey64.exe", "AutoHotkeyU64.exe", "AutoHotkey.exe"]:
            try:
                r = subprocess.run(["where", name], capture_output=True, text=True, timeout=3)
                if r.returncode == 0:
                    f = r.stdout.strip().splitlines()[0].strip()
                    if f and Path(f).exists():
                        self._ahk = f
                        return f
            except Exception:
                pass
        return None

    def _ahk_script(self) -> Path:
        return Path(config.KAKAO_PROJECT_DIR) / "kakao_send.ahk"

    def post(self, target: str, text: str, image_path=None, dry_run: bool = True) -> PostResult:
        if not self._valid_target(target):
            return PostResult(ok=False, blocked=True, error="카카오 방 이름이 비어있음")

        if dry_run:
            self._log_dry("POST", target, text, image_path)
            return PostResult(ok=True, dry_run=True)

        if config.GLOBAL_DRY_RUN:
            return PostResult(ok=False, blocked=True,
                error="GLOBAL_DRY_RUN=1 — 실전송 차단(안전). 켜려면 .env에서 0으로.")
        if not self._rate_ok():
            return PostResult(ok=False, blocked=True,
                error=f"일일 발행 상한({config.DAILY_POST_LIMIT}건) 도달 — 계정 보호")

        files = [image_path] if image_path else None
        ok = self._send_ahk(target, text, files)
        return PostResult(ok=ok, error=None if ok else "AHK 전송 실패(카톡창/AHK 확인)")

    def send_reply(self, target: str, text: str, files=None, dry_run: bool = True) -> bool:
        if dry_run:
            self._log_dry("REPLY", target, text)
            return True
        if config.GLOBAL_DRY_RUN:
            print("[kakao] GLOBAL_DRY_RUN=1 — 실전송 차단")
            return False
        return self._send_ahk(target, text, files)

    def read_feedback(self, target: str, since=None) -> list:
        return []   # TODO(P2): crawler(별표탭) 수집 → Feedback

    # ── AHK 호출 (sender.py 로직 vendoring, config 충돌 회피) ──
    def _send_ahk(self, room_name: str, message: str, files=None) -> bool:
        ahk = self._ahk_exe()
        if not ahk:
            print("[kakao] AutoHotkey 미설치 — autohotkey.com에서 설치 필요")
            return False
        script = self._ahk_script()
        if not script.exists():
            print(f"[kakao] kakao_send.ahk 없음: {script}")
            return False

        valid = [str(Path(p).resolve()) for p in (files or []) if Path(p).exists()]
        msg_path = param_path = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                             delete=False, encoding="utf-8") as f:
                f.write(message)
                msg_path = f.name
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt",
                                             delete=False, encoding="utf-8") as f:
                f.write(f"chatroom={room_name}\n")
                f.write(f"msg_file={msg_path}\n")
                for i, fp in enumerate(valid, 1):
                    f.write(f"file{i}={fp}\n")
                param_path = f.name

            print(f"[kakao] AHK 전송 → '{room_name}' (파일 {len(valid)}개)")
            r = subprocess.run([ahk, str(script), param_path], timeout=120,
                               capture_output=True, text=True, encoding="utf-8")
            return "OK" in (r.stdout or "").strip().splitlines()
        except subprocess.TimeoutExpired:
            print(f"[kakao] 타임아웃(120초): '{room_name}'")
            return False
        except Exception as e:
            print(f"[kakao] 전송 오류: {e}")
            return False
        finally:
            for p in (msg_path, param_path):
                if p:
                    try:
                        os.unlink(p)
                    except Exception:
                        pass
