"""
MainWindow - API Key 자동화 프로그램 메인 창

디자인: GitHub Dark 팔레트 기반 모던 다크 테마
레이아웃:
  - 좌측 사이드패널: 서비스 선택 카드
  - 우측 메인패널: 실시간 로그 + 진행바
  - 하단: 상태바
"""

import json
import sys
import urllib.request
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from PyQt6.QtCore import Qt, QSize, QUrl, QTimer, QThread, pyqtSignal, pyqtSlot
from PyQt6.QtGui import (
    QFont, QIcon, QTextCursor, QColor,
    QPalette, QPixmap, QPainter,
)
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget,
    QHBoxLayout, QVBoxLayout, QLabel,
    QPushButton, QTextEdit, QTextBrowser, QProgressBar,
    QFrame, QCheckBox, QSizePolicy,
    QTabWidget, QScrollArea, QGridLayout,
    QSpacerItem, QInputDialog, QMessageBox, QDialog,
)

from gui.styles import DARK_THEME, LOG_COLORS
from gui.worker import WorkerThread
from security.key_vault import KeyVault
from security.env_manager import EnvManager
from core.session_manager import SessionManager


# ─────────────────────────────────────────
# 버전 정보
# ─────────────────────────────────────────
APP_VERSION = "1.0.0"
GITHUB_REPO  = "sangsu7746/-APIKeyManager"


# ─────────────────────────────────────────
# 업데이트 확인 스레드
# ─────────────────────────────────────────
class UpdateCheckerThread(QThread):
    """앱 시작 시 GitHub Releases API로 최신 버전 조회 (백그라운드)"""
    update_available = pyqtSignal(str, str)   # (latest_version, release_url)

    def run(self):
        try:
            api_url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
            req = urllib.request.Request(
                api_url,
                headers={"User-Agent": f"APIKeyManager/{APP_VERSION}"},
            )
            with urllib.request.urlopen(req, timeout=6) as resp:
                data = json.loads(resp.read().decode())
            latest = data.get("tag_name", "").lstrip("v")
            release_url = data.get("html_url", "")
            if latest and self._is_newer(latest):
                self.update_available.emit(latest, release_url)
        except Exception:
            pass  # 네트워크 오류 시 조용히 무시

    def _is_newer(self, latest: str) -> bool:
        try:
            cur = tuple(int(x) for x in APP_VERSION.split("."))
            new = tuple(int(x) for x in latest.split("."))
            return new > cur
        except Exception:
            return False


# ─────────────────────────────────────────
# 업데이트 알림 다이얼로그
# ─────────────────────────────────────────
class UpdateDialog(QDialog):
    """새 버전 발견 시 표시되는 업데이트 알림 창"""

    def __init__(self, latest: str, url: str, parent=None):
        super().__init__(parent)
        self._url = url
        self.setWindowTitle("업데이트 알림")
        self.setModal(True)
        self.setFixedSize(420, 220)
        self._build_ui(latest)

    def _build_ui(self, latest: str):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 20)
        lay.setSpacing(12)

        title = QLabel("🎉  새 버전이 출시되었습니다!")
        title.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        title.setStyleSheet("color:#e6edf3;")
        lay.addWidget(title)

        info = QLabel(
            f"<p style='color:#8b949e; font-size:13px; margin:0;'>"
            f"현재 버전: <b style='color:#e6edf3;'>v{APP_VERSION}</b>&nbsp;&nbsp;→&nbsp;&nbsp;"
            f"최신 버전: <b style='color:#3fb950;'>v{latest}</b></p>"
        )
        info.setTextFormat(Qt.TextFormat.RichText)
        lay.addWidget(info)

        desc = QLabel("GitHub Releases에서 최신 버전을 다운로드하세요.")
        desc.setStyleSheet("color:#8b949e; font-size:12px;")
        desc.setWordWrap(True)
        lay.addWidget(desc)

        lay.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_later = QPushButton("나중에")
        btn_later.setFixedHeight(36)
        btn_later.setStyleSheet("""
            QPushButton { background:transparent; color:#8b949e;
                          border:1px solid #30363d; border-radius:6px; font-size:13px; }
            QPushButton:hover { color:#e6edf3; }
        """)
        btn_later.clicked.connect(self.reject)
        btn_row.addWidget(btn_later)

        btn_download = QPushButton("⬇  지금 다운로드")
        btn_download.setFixedHeight(36)
        btn_download.setStyleSheet("""
            QPushButton { background:#238636; color:white;
                          border-radius:6px; font-size:13px; font-weight:700; border:none; }
            QPushButton:hover { background:#2ea043; }
        """)
        btn_download.clicked.connect(self._download)
        btn_row.addWidget(btn_download)

        lay.addLayout(btn_row)

    def _download(self):
        webbrowser.open(self._url)
        self.accept()


# ─────────────────────────────────────────
# 첫 실행 안내 다이얼로그
# ─────────────────────────────────────────
class FirstRunDialog(QDialog):
    """최초 실행 시 회원가입 안내 팝업"""

    _FLAG_FILE = Path("vault/.first_run_done")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("시작 전 꼭 읽어주세요")
        self.setModal(True)
        self.setFixedSize(500, 460)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(32, 28, 32, 24)
        layout.setSpacing(14)

        # 제목
        title = QLabel("🔑  API Key 자동화 프로그램")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #e6edf3;")
        layout.addWidget(title)

        sub = QLabel("사용 전 아래 안내를 확인해 주세요.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(sub)

        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #21262d; border: none; max-height: 1px;")
        layout.addWidget(line)

        # 안내 본문
        body = QLabel(
            "이 프로그램은 각 서비스의 API Key를 자동으로 발급합니다.\n"
            "자동화 전에 아래 서비스에 <b>미리 회원가입</b>이 필요합니다.\n"
        )
        body.setWordWrap(True)
        body.setStyleSheet("color: #e6edf3; font-size: 13px; line-height: 1.5;")
        body.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(body)

        # 서비스 목록
        services_html = (
            "<table cellspacing='6' style='font-size:13px; color:#e6edf3;'>"
            "<tr><td>🤖</td><td><b>Anthropic Claude</b></td><td style='color:#8b949e; padding-left:8px;'>console.anthropic.com</td></tr>"
            "<tr><td>🧠</td><td><b>OpenAI GPT</b></td><td style='color:#8b949e; padding-left:8px;'>platform.openai.com</td></tr>"
            "<tr><td>✨</td><td><b>Google Gemini</b></td><td style='color:#8b949e; padding-left:8px;'>aistudio.google.com</td></tr>"
            "<tr><td>🐙</td><td><b>GitHub Token</b></td><td style='color:#8b949e; padding-left:8px;'>github.com</td></tr>"
            "<tr><td>☁️</td><td><b>AWS IAM</b></td><td style='color:#8b949e; padding-left:8px;'>aws.amazon.com</td></tr>"
            "</table>"
        )
        svc_lbl = QLabel(services_html)
        svc_lbl.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(svc_lbl)

        # 구분선
        line2 = QFrame()
        line2.setFrameShape(QFrame.Shape.HLine)
        line2.setStyleSheet("background: #21262d; border: none; max-height: 1px;")
        layout.addWidget(line2)

        # 구글 추천 안내
        tip_box = QLabel(
            "💡  <b>빠른 가입 팁</b><br>"
            "<span style='color:#e6edf3;'>"
            "위 서비스 대부분이 <b style='color:#4285f4;'>Google 계정으로 1클릭 가입</b>을 지원합니다.<br>"
            "구글 아이디가 있다면 별도 이메일 인증 없이 즉시 가입할 수 있어 가장 빠릅니다."
            "</span>"
        )
        tip_box.setTextFormat(Qt.TextFormat.RichText)
        tip_box.setWordWrap(True)
        tip_box.setStyleSheet("""
            background: #0d1117;
            border: 1px solid #1f6feb;
            border-radius: 8px;
            padding: 12px 14px;
            font-size: 13px;
            color: #8b949e;
            line-height: 1.5;
        """)
        layout.addWidget(tip_box)

        layout.addStretch()

        # 확인 버튼
        btn = QPushButton("확인했습니다 — 시작하기")
        btn.setFixedHeight(42)
        btn.setStyleSheet("""
            QPushButton {
                background: #1f6feb;
                color: white;
                border-radius: 8px;
                font-size: 14px;
                font-weight: 700;
                border: none;
            }
            QPushButton:hover { background: #388bfd; }
        """)
        btn.clicked.connect(self._confirm)
        layout.addWidget(btn)

    def _confirm(self):
        self._FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._FLAG_FILE.touch()
        self.accept()

    @classmethod
    def should_show(cls) -> bool:
        return not cls._FLAG_FILE.exists()


# ─────────────────────────────────────────
# D안: 광고 카운트다운 다이얼로그
# ─────────────────────────────────────────
class AdCountdownDialog(QDialog):
    """복사 전 5초 카운트다운 — 브라우저에서 광고 페이지 오픈"""

    COUNTDOWN    = 5
    THANK_YOU_URL = "https://apikeymanager-web.vercel.app/thank-you"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("잠깐! 광고를 확인해 주세요")
        self.setModal(True)
        self.setFixedSize(420, 200)
        self._remaining = self.COUNTDOWN
        self._build_ui()
        webbrowser.open(self.THANK_YOU_URL)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        msg = QLabel("브라우저에서 광고 페이지가 열렸습니다.\n잠시 확인 후 자동으로 복사됩니다.")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet("font-size: 14px; color: #e6edf3;")
        layout.addWidget(msg)

        self.progress = QProgressBar()
        self.progress.setRange(0, self.COUNTDOWN)
        self.progress.setValue(0)
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        layout.addWidget(self.progress)

        self.lbl_count = QLabel(f"⏱ {self.COUNTDOWN}초 후 클립보드에 복사됩니다...")
        self.lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_count.setStyleSheet("color: #8b949e; font-size: 13px;")
        layout.addWidget(self.lbl_count)

    def _tick(self):
        self._remaining -= 1
        self.progress.setValue(self.COUNTDOWN - self._remaining)
        self.lbl_count.setText(f"⏱ {self._remaining}초 후 클립보드에 복사됩니다...")
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()


# ─────────────────────────────────────────
# C안: 복사 완료 후원 다이얼로그
# ─────────────────────────────────────────
class DonationDialog(QDialog):
    """복사 완료 후 후원 팝업"""

    KOFI_URL = "https://ko-fi.com/headjim"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("복사 완료")
        self.setModal(True)
        self.setFixedSize(380, 230)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(10)

        icon = QLabel("✅")
        icon.setFont(QFont("Segoe UI Emoji", 28))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(icon)

        title = QLabel("클립보드에 복사됐습니다!")
        title.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("color: #e6edf3;")
        layout.addWidget(title)

        sub = QLabel("이 앱이 도움이 됐나요?  개발자에게 커피 한 잔 ☕")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(sub)

        btn_kofi = QPushButton("☕  Ko-fi로 후원하기")
        btn_kofi.setFixedHeight(40)
        btn_kofi.setStyleSheet("""
            QPushButton { background:#FF5E5B; color:white; border-radius:8px;
                          font-weight:700; font-size:14px; border:none; }
            QPushButton:hover { background:#e54e4b; }
        """)
        btn_kofi.clicked.connect(self._open_kofi)
        layout.addWidget(btn_kofi)

        skip = QPushButton("괜찮아요, 다음에")
        skip.setFixedHeight(30)
        skip.setStyleSheet("""
            QPushButton { background:transparent; color:#8b949e;
                          border:1px solid #30363d; border-radius:6px; font-size:12px; }
            QPushButton:hover { color:#e6edf3; }
        """)
        skip.clicked.connect(self.reject)
        layout.addWidget(skip)

    def _open_kofi(self):
        webbrowser.open(self.KOFI_URL)
        self.accept()


# ─────────────────────────────────────────
# 서비스별 회원가입 안내 정보
# ─────────────────────────────────────────
SIGNUP_INFO = {
    "anthropic": {
        "signup_url": "https://console.anthropic.com",
        "google_ok": True,
        "card_required": False,
        "free_credit": "$5 무료 크레딧 제공",
        "steps": [
            "우측 상단 'Sign up' 버튼 클릭",
            "Google 계정으로 가입 클릭 (추천) 또는 이메일 입력",
            "비밀번호 설정 (영문+숫자+특수문자 8자 이상)",
            "이메일 인증 링크 클릭 (받은 편지함 확인)",
            "이름 / 사용 목적 선택 후 완료",
        ],
        "warnings": [
            "카드 정보 불필요 — 무료로 가입 가능합니다",
            "가입 즉시 $5 무료 크레딧 자동 제공됩니다",
            "Google 계정으로 가입하면 1분 이내 완료됩니다",
        ],
    },
    "openai": {
        "signup_url": "https://platform.openai.com/signup",
        "google_ok": True,
        "card_required": True,
        "free_credit": "$5 무료 크레딧 제공",
        "steps": [
            "'Sign up' 버튼 클릭",
            "Google 계정으로 가입 클릭 (추천) 또는 이메일 입력",
            "이메일 인증 링크 클릭 (받은 편지함 확인)",
            "이름 / 생년월일 입력",
            "신용카드 등록 (API 사용을 위해 필수)",
        ],
        "warnings": [
            "카드 등록이 필요합니다 (즉시 청구되지 않습니다)",
            "가입 후 $5 무료 크레딧이 자동 지급됩니다",
            "카드 등록 없이는 API Key 발급이 불가합니다",
            "Google 계정으로 가입하면 이메일 인증이 생략됩니다",
        ],
    },
    "gemini": {
        "signup_url": "https://aistudio.google.com",
        "google_ok": True,
        "card_required": False,
        "free_credit": "무료 사용 가능 (분당 요청 제한)",
        "steps": [
            "Google 계정으로 자동 로그인 (별도 가입 불필요)",
            "'Sign in with Google' 클릭",
            "사용할 Google 계정 선택",
            "서비스 이용 약관 동의 후 완료",
        ],
        "warnings": [
            "Google 계정만 있으면 별도 가입 없이 즉시 사용 가능합니다",
            "카드 정보 불필요 — 완전 무료입니다",
            "분당 요청 수 제한이 있지만 개인 사용에는 충분합니다",
        ],
    },
    "github": {
        "signup_url": "https://github.com/signup",
        "google_ok": True,
        "card_required": False,
        "free_credit": "무료 계정 제공",
        "steps": [
            "이메일 주소 입력",
            "비밀번호 설정",
            "사용자 이름(닉네임) 설정",
            "이메일 수신 여부 선택",
            "CAPTCHA 풀기 (퍼즐 형태)",
            "이메일 인증 코드 입력 (받은 편지함 확인)",
        ],
        "warnings": [
            "카드 정보 불필요 — 완전 무료입니다",
            "사용자 이름은 나중에 변경하기 어려우니 신중히 정하세요",
            "이메일 인증 코드가 스팸함에 있을 수 있습니다",
        ],
    },
    "aws": {
        "signup_url": "https://aws.amazon.com/free",
        "google_ok": False,
        "card_required": True,
        "free_credit": "12개월 무료 티어 제공",
        "steps": [
            "'무료로 시작' 버튼 클릭",
            "이메일 주소 및 계정 이름 입력",
            "비밀번호 설정",
            "연락처 정보 입력 (이름, 주소, 전화번호)",
            "신용카드 정보 입력 (즉시 청구 안 됨, $1 임시 확인만)",
            "전화번호 인증 (문자 또는 전화 선택)",
            "지원 플랜 선택 — '기본 지원 무료' 선택",
        ],
        "warnings": [
            "카드 등록 필수 — $1 임시 인증 후 즉시 취소됩니다",
            "무료 티어 한도 초과 시 요금이 발생할 수 있습니다",
            "가입 완료까지 5~10분 소요됩니다",
            "Google 계정 가입을 지원하지 않습니다",
            "지원 플랜은 반드시 '기본 지원 무료'를 선택하세요",
        ],
    },
}


# ─────────────────────────────────────────
# 가입 안내 다이얼로그
# ─────────────────────────────────────────
class SignupGuideDialog(QDialog):
    """서비스별 회원가입 단계 안내 다이얼로그"""

    def __init__(self, services: List[str], parent=None):
        super().__init__(parent)
        self.services = services
        self._idx = 0
        self.setWindowTitle("서비스 회원가입 안내")
        self.setModal(True)
        self.setFixedSize(680, 560)
        self._build_ui()
        self._show_service(0)

    def _build_ui(self):
        root = QHBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── 왼쪽: 서비스 진행 목록
        left = QWidget()
        left.setFixedWidth(170)
        left.setStyleSheet("background:#0d1117; border-right:1px solid #21262d;")
        left_lay = QVBoxLayout(left)
        left_lay.setContentsMargins(12, 20, 12, 20)
        left_lay.setSpacing(6)

        lbl = QLabel("진행 현황")
        lbl.setStyleSheet("color:#8b949e; font-size:11px; font-weight:700;")
        left_lay.addWidget(lbl)

        self._step_labels: List[QLabel] = []
        for sid in self.services:
            info = SERVICES[sid]
            lbl = QLabel(f"{info['icon']}  {info['name']}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#484f58; font-size:12px; padding:6px 4px; border-radius:4px;")
            left_lay.addWidget(lbl)
            self._step_labels.append(lbl)

        left_lay.addStretch()
        root.addWidget(left)

        # ── 오른쪽: 안내 내용
        right = QWidget()
        right.setStyleSheet("background:#161b22;")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(24, 24, 24, 20)
        right_lay.setSpacing(12)

        # 구글 계정 공통 추천 안내 (항상 표시)
        lbl_recommend = QLabel(
            "💡  <b>Google 계정 이메일로 가입을 추천합니다</b> — "
            "별도 비밀번호 없이 기존 구글 계정 하나로 대부분의 서비스에 빠르게 가입할 수 있습니다."
        )
        lbl_recommend.setWordWrap(True)
        lbl_recommend.setTextFormat(Qt.TextFormat.RichText)
        lbl_recommend.setStyleSheet("""
            background:#1a2332; color:#c9d1d9;
            border:1px solid #2d5a8e; border-radius:6px;
            padding:8px 12px; font-size:12px;
        """)
        right_lay.addWidget(lbl_recommend)

        # 서비스 이름 + 진행 표시
        top_row = QHBoxLayout()
        self.lbl_service = QLabel()
        self.lbl_service.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        self.lbl_service.setStyleSheet("color:#e6edf3;")
        top_row.addWidget(self.lbl_service)
        top_row.addStretch()
        self.lbl_progress = QLabel()
        self.lbl_progress.setStyleSheet("color:#8b949e; font-size:12px;")
        top_row.addWidget(self.lbl_progress)
        right_lay.addLayout(top_row)

        # 서비스별 Google 가입 가능 여부 뱃지
        self.lbl_google = QLabel("✅  Google 계정으로 1클릭 가입 가능 — 가장 빠릅니다")
        self.lbl_google.setStyleSheet("""
            background:#0d2230; color:#58a6ff;
            border:1px solid #1f6feb; border-radius:6px;
            padding:6px 10px; font-size:12px;
        """)
        right_lay.addWidget(self.lbl_google)

        # 단계별 안내
        steps_lbl = QLabel("📝  입력 순서")
        steps_lbl.setStyleSheet("color:#8b949e; font-size:11px; font-weight:700; margin-top:4px;")
        right_lay.addWidget(steps_lbl)

        self.lbl_steps = QLabel()
        self.lbl_steps.setWordWrap(True)
        self.lbl_steps.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_steps.setStyleSheet("""
            background:#0d1117; color:#e6edf3;
            border:1px solid #21262d; border-radius:6px;
            padding:10px 14px; font-size:13px; line-height:1.6;
        """)
        right_lay.addWidget(self.lbl_steps)

        # 주의사항
        warn_lbl = QLabel("⚠️  주의사항")
        warn_lbl.setStyleSheet("color:#8b949e; font-size:11px; font-weight:700; margin-top:4px;")
        right_lay.addWidget(warn_lbl)

        self.lbl_warnings = QLabel()
        self.lbl_warnings.setWordWrap(True)
        self.lbl_warnings.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_warnings.setStyleSheet("""
            background:#1c1107; color:#e3b341;
            border:1px solid #3d2b00; border-radius:6px;
            padding:10px 14px; font-size:12px; line-height:1.6;
        """)
        right_lay.addWidget(self.lbl_warnings)

        right_lay.addStretch()

        # 버튼 영역
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        self.btn_browser = QPushButton("🌐  브라우저 다시 열기")
        self.btn_browser.setFixedHeight(36)
        self.btn_browser.setStyleSheet("""
            QPushButton { background:#21262d; color:#e6edf3;
                          border:1px solid #30363d; border-radius:6px; font-size:13px; }
            QPushButton:hover { background:#30363d; }
        """)
        self.btn_browser.clicked.connect(self._open_browser)
        btn_row.addWidget(self.btn_browser)

        btn_row.addStretch()

        self.btn_skip = QPushButton("건너뛰기")
        self.btn_skip.setFixedHeight(36)
        self.btn_skip.setFixedWidth(90)
        self.btn_skip.setStyleSheet("""
            QPushButton { background:transparent; color:#8b949e;
                          border:1px solid #30363d; border-radius:6px; font-size:12px; }
            QPushButton:hover { color:#e6edf3; }
        """)
        self.btn_skip.clicked.connect(self._next)
        btn_row.addWidget(self.btn_skip)

        self.btn_next = QPushButton("✅  가입 완료 — 다음으로")
        self.btn_next.setFixedHeight(36)
        self.btn_next.setStyleSheet("""
            QPushButton { background:#238636; color:white;
                          border-radius:6px; font-size:13px; font-weight:700; border:none; }
            QPushButton:hover { background:#2ea043; }
        """)
        self.btn_next.clicked.connect(self._next)
        btn_row.addWidget(self.btn_next)

        right_lay.addLayout(btn_row)
        root.addWidget(right)

    def _show_service(self, idx: int):
        if idx >= len(self.services):
            self._finish()
            return

        sid = self.services[idx]
        info = SERVICES[sid]
        guide = SIGNUP_INFO[sid]

        # 진행 목록 업데이트
        for i, lbl in enumerate(self._step_labels):
            if i < idx:
                lbl.setStyleSheet("color:#3fb950; font-size:12px; padding:6px 4px;")
            elif i == idx:
                lbl.setStyleSheet(
                    "color:#e6edf3; font-size:12px; font-weight:700; "
                    "padding:6px 4px; background:#21262d; border-radius:4px;"
                )
            else:
                lbl.setStyleSheet("color:#484f58; font-size:12px; padding:6px 4px;")

        # 서비스 이름
        self.lbl_service.setText(f"{info['icon']}  {info['name']}")
        self.lbl_progress.setText(f"{idx + 1} / {len(self.services)}")

        # Google 가입 뱃지
        if guide["google_ok"]:
            self.lbl_google.setText("✅  Google 계정으로 1클릭 가입 가능 — 가장 빠릅니다")
            self.lbl_google.setStyleSheet("""
                background:#0d2230; color:#58a6ff;
                border:1px solid #1f6feb; border-radius:6px;
                padding:6px 10px; font-size:12px;
            """)
        else:
            self.lbl_google.setText("ℹ️  Google 계정 가입을 지원하지 않습니다 — 이메일로 가입하세요")
            self.lbl_google.setStyleSheet("""
                background:#1c1107; color:#e3b341;
                border:1px solid #3d2b00; border-radius:6px;
                padding:6px 10px; font-size:12px;
            """)

        # 단계 안내
        steps_html = "".join(
            f"<p style='margin:2px 0;'><b style='color:#58a6ff;'>{i+1}.</b>  {s}</p>"
            for i, s in enumerate(guide["steps"])
        )
        if guide.get("free_credit"):
            steps_html += f"<p style='margin:6px 0 0 0; color:#3fb950;'>🎁  {guide['free_credit']}</p>"
        self.lbl_steps.setText(steps_html)

        # 주의사항
        warn_html = "".join(
            f"<p style='margin:2px 0;'>•  {w}</p>"
            for w in guide["warnings"]
        )
        self.lbl_warnings.setText(warn_html)

        # 마지막 서비스면 버튼 문구 변경
        if idx == len(self.services) - 1:
            self.btn_next.setText("✅  가입 완료 — 닫기")
        else:
            self.btn_next.setText("✅  가입 완료 — 다음으로")

        # 브라우저 자동 오픈
        self._open_browser()

    def _open_browser(self):
        sid = self.services[self._idx]
        webbrowser.open(SIGNUP_INFO[sid]["signup_url"])

    def _next(self):
        self._idx += 1
        self._show_service(self._idx)

    def _finish(self):
        QMessageBox.information(
            self,
            "가입 안내 완료",
            "모든 서비스 가입 안내가 완료되었습니다.\n"
            "이제 서비스를 선택하고 '▶ 자동화 시작'을 눌러 API 키를 발급받으세요.",
        )
        self.accept()


# ─────────────────────────────────────────
# 서비스 정의
# ─────────────────────────────────────────
SERVICES = {
    "anthropic": {
        "name":    "Anthropic Claude",
        "icon":    "🤖",
        "color":   "#cc785c",
        "desc":    "console.anthropic.com",
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "name":    "Google Gemini",
        "icon":    "✨",
        "color":   "#4285f4",
        "desc":    "aistudio.google.com",
        "env_key": "GEMINI_API_KEY",
    },
    "openai": {
        "name":    "OpenAI",
        "icon":    "🧠",
        "color":   "#10a37f",
        "desc":    "platform.openai.com",
        "env_key": "OPENAI_API_KEY",
    },
    "github": {
        "name":    "GitHub Token",
        "icon":    "🐙",
        "color":   "#e6edf3",
        "desc":    "github.com/settings/tokens",
        "env_key": "GITHUB_TOKEN",
    },
    "aws": {
        "name":    "AWS IAM",
        "icon":    "☁️",
        "color":   "#ff9900",
        "desc":    "console.aws.amazon.com",
        "env_key": "AWS_ACCESS_KEY_ID",
    },
}


# ─────────────────────────────────────────
# 서비스 카드 위젯
# ─────────────────────────────────────────
class ServiceCard(QFrame):
    """체크박스 + 서비스 정보를 담은 카드 위젯"""

    def __init__(self, service_id: str, info: dict, parent=None):
        super().__init__(parent)
        self.service_id = service_id
        self.info = info
        self.setObjectName("serviceCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build_ui()

    def _build_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(8)

        # 체크박스
        self.checkbox = QCheckBox()
        self.checkbox.setChecked(False)
        self.checkbox.stateChanged.connect(self._on_check)
        layout.addWidget(self.checkbox)

        # 아이콘 레이블
        icon_lbl = QLabel(self.info["icon"])
        icon_lbl.setFont(QFont("Segoe UI Emoji", 18))
        icon_lbl.setFixedWidth(28)
        layout.addWidget(icon_lbl)

        # 이름 + 설명
        text_layout = QVBoxLayout()
        text_layout.setSpacing(1)

        name_lbl = QLabel(self.info["name"])
        name_lbl.setObjectName("serviceNameLabel")
        text_layout.addWidget(name_lbl)

        desc_lbl = QLabel(self.info["desc"])
        desc_lbl.setStyleSheet("color: #8b949e; font-size: 11px;")
        text_layout.addWidget(desc_lbl)

        layout.addLayout(text_layout, stretch=1)

        # 상태 뱃지 (너비 고정)
        self.badge = QLabel("대기")
        self.badge.setFixedWidth(50)
        self.badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.badge.setStyleSheet("""
            background: #21262d;
            color: #8b949e;
            border-radius: 4px;
            padding: 2px 4px;
            font-size: 11px;
            font-weight: 600;
        """)
        layout.addWidget(self.badge)

    def _on_check(self, state):
        selected = state == Qt.CheckState.Checked.value
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_badge(self, text: str, color: str = "#8b949e", bg: str = "#21262d"):
        self.badge.setText(text)
        self.badge.setStyleSheet(f"""
            background: {bg};
            color: {color};
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 11px;
            font-weight: 600;
        """)

    def set_running(self):
        self.set_badge("실행 중...", "#d29922", "#272115")

    def set_success(self):
        self.set_badge("✅ 완료", "#3fb950", "#0f2419")

    def set_failed(self):
        self.set_badge("❌ 실패", "#f85149", "#2d0e0d")

    def reset(self):
        self.set_badge("대기", "#8b949e", "#21262d")

    def mousePressEvent(self, event):
        self.checkbox.toggle()
        super().mousePressEvent(event)


# ─────────────────────────────────────────
# 메인 윈도우
# ─────────────────────────────────────────
class MainWindow(QMainWindow):
    """API Key 자동화 프로그램 메인 윈도우"""

    def __init__(self):
        super().__init__()
        self._worker: WorkerThread | None = None
        self._cards: Dict[str, ServiceCard] = {}
        self._vault = KeyVault()
        self._env_mgr = EnvManager()
        self._session_mgr = SessionManager()

        self._setup_window()
        self._build_ui()
        self._refresh_key_status()

        if FirstRunDialog.should_show():
            FirstRunDialog(self).exec()

        # 업데이트 확인 (백그라운드, 5초 후 시작)
        QTimer.singleShot(5000, self._check_update)

    # ─────────────────────────────────────────
    # 윈도우 설정
    # ─────────────────────────────────────────
    def _setup_window(self):
        self.setWindowTitle("API Key 자동화 프로그램")
        self.setMinimumSize(900, 620)
        self.resize(1100, 700)

    # ─────────────────────────────────────────
    # UI 빌드
    # ─────────────────────────────────────────
    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ── 헤더바
        root_layout.addWidget(self._build_header())

        # ── 메인 영역 (사이드 + 콘텐츠)
        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        body_layout.addWidget(self._build_side_panel(), stretch=0)
        body_layout.addWidget(self._build_main_panel(), stretch=1)
        root_layout.addWidget(body, stretch=1)

        # ── 상태바
        root_layout.addWidget(self._build_status_bar())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("headerBar")
        header.setFixedHeight(56)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(20, 0, 20, 0)

        # 로고 + 타이틀
        title = QLabel("🔑  API Key 자동화 프로그램")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        layout.addStretch()

        # 버전 태그
        ver = QLabel("v1.0")
        ver.setStyleSheet("color: #8b949e; font-size: 12px;")
        layout.addWidget(ver)

        return header

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidePanel")
        panel.setFixedWidth(290)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 20, 16, 20)
        layout.setSpacing(12)

        # 서비스 선택 타이틀
        sec_lbl = QLabel("서비스 선택")
        sec_lbl.setObjectName("sectionLabel")
        layout.addWidget(sec_lbl)

        # 서비스 카드들
        for sid, info in SERVICES.items():
            card = ServiceCard(sid, info)
            self._cards[sid] = card
            layout.addWidget(card)

        # 구분선
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #21262d; background: #21262d; border: none; max-height: 1px;")
        layout.addWidget(line)

        # 전체 선택 / 해제
        sel_layout = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_all.setFixedHeight(30)
        btn_all.clicked.connect(lambda: [c.checkbox.setChecked(True) for c in self._cards.values()])

        btn_none = QPushButton("전체 해제")
        btn_none.setFixedHeight(30)
        btn_none.clicked.connect(lambda: [c.checkbox.setChecked(False) for c in self._cards.values()])

        sel_layout.addWidget(btn_all)
        sel_layout.addWidget(btn_none)
        layout.addLayout(sel_layout)

        layout.addStretch()

        # 가입 안내 버튼
        self.btn_signup = QPushButton("🆕  서비스 가입 안내")
        self.btn_signup.setObjectName("btnSignup")
        self.btn_signup.setFixedHeight(38)
        self.btn_signup.setToolTip("선택한 서비스의 회원가입을 단계별로 안내합니다")
        self.btn_signup.clicked.connect(self._on_signup_guide)
        self.btn_signup.setStyleSheet("""
            QPushButton#btnSignup {
                background: #1c2b3a;
                color: #58a6ff;
                border: 1px solid #1f6feb;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 600;
            }
            QPushButton#btnSignup:hover {
                background: #1f6feb;
                color: white;
            }
        """)
        layout.addWidget(self.btn_signup)

        # 구분선
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #21262d; background: #21262d; border: none; max-height: 1px;")
        layout.addWidget(sep)

        # 시작 / 중단 버튼
        self.btn_start = QPushButton("▶  자동화 시작")
        self.btn_start.setObjectName("btnStart")
        self.btn_start.setFixedHeight(44)
        self.btn_start.clicked.connect(self._on_start)
        layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("■  중단")
        self.btn_stop.setObjectName("btnStop")
        self.btn_stop.setFixedHeight(36)
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        layout.addWidget(self.btn_stop)

        return panel

    def _build_main_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("mainPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # 탭 위젯
        tabs = QTabWidget()
        tabs.addTab(self._build_log_tab(), "📋  실행 로그")
        tabs.addTab(self._build_keys_tab(), "🔐  저장된 키")
        layout.addWidget(tabs, stretch=1)

        # 진행바 영역
        prog_widget = QWidget()
        prog_layout = QVBoxLayout(prog_widget)
        prog_layout.setContentsMargins(0, 0, 0, 0)
        prog_layout.setSpacing(4)

        self.progress_label = QLabel("준비 완료")
        self.progress_label.setStyleSheet("color: #8b949e; font-size: 12px;")
        prog_layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setTextVisible(False)
        prog_layout.addWidget(self.progress_bar)

        layout.addWidget(prog_widget)

        return panel

    def _build_log_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        # 로그 뷰어
        self.log_view = QTextEdit()
        self.log_view.setObjectName("logViewer")
        self.log_view.setReadOnly(True)
        self.log_view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self.log_view)

        # 로그 하단 버튼
        btn_clear = QPushButton("로그 지우기")
        btn_clear.setFixedWidth(100)
        btn_clear.setFixedHeight(28)
        btn_clear.clicked.connect(self.log_view.clear)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_clear)
        layout.addLayout(btn_row)

        return widget

    def _build_keys_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(12)

        # 저장된 키 목록 텍스트 뷰
        self.keys_view = QTextBrowser()
        self.keys_view.setObjectName("logViewer")
        self.keys_view.setOpenLinks(False)
        self.keys_view.anchorClicked.connect(self._on_copy_key)
        layout.addWidget(self.keys_view)

        # 새로고침 버튼
        btn_refresh = QPushButton("🔄  새로고침")
        btn_refresh.setFixedWidth(120)
        btn_refresh.setFixedHeight(28)
        btn_refresh.clicked.connect(self._refresh_key_status)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(btn_refresh)
        layout.addLayout(btn_row)

        return widget

    def _build_status_bar(self) -> QWidget:
        bar = QWidget()
        bar.setObjectName("statusBar")
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 0, 16, 0)

        self.status_label = QLabel("준비 완료 — 서비스를 선택하고 자동화를 시작하세요.")
        self.status_label.setObjectName("statusLabel")
        layout.addWidget(self.status_label)
        layout.addStretch()

        # 시계
        from PyQt6.QtCore import QTimer
        self._clock = QLabel()
        self._clock.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(self._clock)
        timer = QTimer(self)
        timer.timeout.connect(self._update_clock)
        timer.start(1000)
        self._update_clock()

        return bar

    # ─────────────────────────────────────────
    # 슬롯 / 이벤트
    # ─────────────────────────────────────────
    def _check_update(self):
        self._updater = UpdateCheckerThread()
        self._updater.update_available.connect(self._on_update_available)
        self._updater.start()

    def _on_update_available(self, version: str, url: str):
        UpdateDialog(version, url, self).exec()

    def _on_signup_guide(self):
        """선택한 서비스의 회원가입 단계 안내 다이얼로그 실행"""
        selected = [sid for sid, card in self._cards.items() if card.is_checked()]
        if not selected:
            QMessageBox.information(
                self,
                "서비스 미선택",
                "가입 안내를 받을 서비스를 먼저 체크해주세요.\n"
                "왼쪽 사이드패널에서 원하는 서비스를 선택하세요.",
            )
            return
        SignupGuideDialog(selected, self).exec()

    def _on_start(self):
        selected = [sid for sid, card in self._cards.items() if card.is_checked()]
        if not selected:
            self._append_log("서비스를 하나 이상 선택하세요.", "WARNING")
            return

        # 프로젝트명 입력 (취소 시 중단)
        project_name = self._ask_project_name(selected)
        if project_name is None:
            return

        # 카드 상태 초기화
        for sid in selected:
            self._cards[sid].reset()
            self._cards[sid].set_running()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"실행 중: {len(selected)}개 서비스...")
        self.status_label.setText("🔄 자동화 실행 중...")

        label = project_name if project_name else "(자동 이름)"
        self._append_log(
            f"▶ 자동화 시작: {', '.join(s.upper() for s in selected)}  |  프로젝트: {label}", "INFO"
        )

        # 워커 스레드 실행
        self._worker = WorkerThread(selected, project_name=project_name)
        self._worker.log_message.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.service_done.connect(self._on_service_done)
        self._worker.all_done.connect(self._on_all_done)
        self._worker.start()

    def _ask_project_name(self, selected: List[str]) -> Optional[str]:
        """
        프로젝트명 입력 팝업.
        반환값: 입력된 이름(str) / 빈 문자열(자동 이름) / None(취소)
        """
        while True:
            name, ok = QInputDialog.getText(
                self,
                "프로젝트 명 입력",
                "프로젝트 명을 입력하세요.\n(비워두면 자동 이름으로 진행됩니다)",
            )
            if not ok:
                return None

            name = name.strip()

            if not name:
                return ""

            # 같은 서비스 내 중복 체크
            vault_keys = self._vault.list_keys()
            conflicts: dict = {}
            for service in selected:
                matches = [k for k in vault_keys.get(service, []) if k.startswith(name)]
                if matches:
                    conflicts[service] = matches

            if not conflicts:
                return name

            # 중복 경고 — 해당 서비스 목록 표시
            detail_lines = []
            for service, keys in conflicts.items():
                info = SERVICES[service]
                detail_lines.append(f"{info['icon']} {info['name']}: {len(keys)}개")
                for k in keys:
                    detail_lines.append(f"   • {k}")

            msg = QMessageBox(self)
            msg.setIcon(QMessageBox.Icon.Warning)
            msg.setWindowTitle("중복 경고")
            msg.setText(f'"{name}" 이름으로 발급된 키가 이미 존재합니다.')
            msg.setInformativeText("\n".join(detail_lines))
            btn_retry = msg.addButton("다시 입력", QMessageBox.ButtonRole.AcceptRole)
            msg.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            msg.exec()

            if msg.clickedButton() != btn_retry:
                return None
            # 다시 입력 → 루프 반복

    def _on_stop(self):
        if self._worker:
            self._worker.stop()
            self.btn_stop.setEnabled(False)
            self.status_label.setText("⛔ 중단 요청됨...")

    @pyqtSlot(str, str)
    def _append_log(self, message: str, level: str = "INFO"):
        """로그 뷰어에 컬러 메시지 추가"""
        color = LOG_COLORS.get(level, "#e6edf3")
        timestamp = datetime.now().strftime("%H:%M:%S")

        level_icons = {
            "INFO":    "ℹ",
            "SUCCESS": "✅",
            "WARNING": "⚠",
            "ERROR":   "❌",
            "DEBUG":   "·",
        }
        icon = level_icons.get(level, "·")

        html = (
            f'<span style="color:#484f58;">[{timestamp}]</span> '
            f'<span style="color:{color};">{icon} {message}</span><br>'
        )

        self.log_view.moveCursor(QTextCursor.MoveOperation.End)
        self.log_view.insertHtml(html)
        self.log_view.moveCursor(QTextCursor.MoveOperation.End)

    @pyqtSlot(int, int)
    def _on_progress(self, done: int, total: int):
        pct = int(done / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_label.setText(f"진행: {done}/{total} 서비스 완료")

    @pyqtSlot(str, bool)
    def _on_service_done(self, service: str, success: bool):
        card = self._cards.get(service)
        if card:
            if success:
                card.set_success()
            else:
                card.set_failed()

    @pyqtSlot()
    def _on_all_done(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.progress_label.setText("모든 작업 완료")
        self.status_label.setText("✅ 자동화 완료")
        self._append_log("━━ 전체 작업 완료 ━━", "SUCCESS")
        self._refresh_key_status()

    def _refresh_key_status(self):
        """저장된 키 탭 새로고침"""
        self.keys_view.clear()
        vault_keys = self._vault.list_keys()
        env_configured = self._env_mgr.list_configured()
        session_info = self._session_mgr.get_session_info()

        if not vault_keys and not env_configured:
            self.keys_view.setHtml(
                '<p style="color:#8b949e; padding:8px;">저장된 API Key가 없습니다.</p>'
            )
            return

        html = ""
        for sid, info in SERVICES.items():
            icon = info["icon"]
            name = info["name"]
            color = info["color"]

            # vault 키 목록
            vault_list = vault_keys.get(sid, [])
            # .env 설정 여부
            env_info = env_configured.get(sid)
            # 세션 유효 여부
            sess = session_info.get(sid, {})
            sess_valid = sess.get("valid", False)

            html += f"""
            <div style='
                background: #161b22;
                border: 1px solid #21262d;
                border-radius: 8px;
                padding: 12px 16px;
                margin-bottom: 10px;
            '>
                <div style='font-size:15px; font-weight:700; color:{color}; margin-bottom:6px;'>
                    {icon} {name}
                </div>
            """

            if vault_list:
                html += f"<div style='color:#8b949e; font-size:11px; margin-bottom:4px;'>🔐 저장된 키: {len(vault_list)}개</div>"
                for k in vault_list:
                    k_enc = quote(k, safe="")
                    html += (
                        f"<table width='100%' cellpadding='0' cellspacing='0' style='margin:1px 0;'>"
                        f"<tr>"
                        f"<td style='color:#e6edf3; font-size:12px; padding-left:12px;'>• {k}</td>"
                        f"<td align='right'>"
                        f"<a href='copy://{sid}/{k_enc}' style='color:#58a6ff; font-size:11px; text-decoration:none;'>📋 복사</a>"
                        f"</td>"
                        f"</tr>"
                        f"</table>"
                    )
            else:
                html += "<div style='color:#484f58; font-size:12px;'>저장된 키 없음</div>"

            if env_info:
                html += f"<div style='color:#3fb950; font-size:12px; margin-top:4px;'>✅ .env: {env_info['env_var']} = {env_info['value']}</div>"

            if sess_valid:
                html += f"<div style='color:#58a6ff; font-size:12px;'>🌐 세션: 유효 (만료: {sess.get('expires_at','?')[:10]})</div>"

            html += "</div>"

        self.keys_view.setHtml(
            f'<div style="font-family: \'Segoe UI\',sans-serif; color:#e6edf3; padding:4px;">{html}</div>'
        )

    @pyqtSlot(QUrl)
    def _on_copy_key(self, url: QUrl):
        service = url.host()
        key_name = unquote(url.path().lstrip("/"))
        value = self._vault.retrieve_key(service, key_name)
        if value:
            # D안: 광고 카운트다운 (브라우저 오픈 + 5초 대기)
            AdCountdownDialog(self).exec()

            # 카운트다운 완료 후 클립보드 복사
            QApplication.clipboard().setText(value)
            self.status_label.setText(f"📋 [{service}] '{key_name}' 클립보드에 복사됨")
            self._append_log(f"📋 [{service}] '{key_name}' 클립보드 복사 완료", "SUCCESS")

            # C안: 후원 팝업
            DonationDialog(self).exec()
        else:
            self.status_label.setText(f"⚠ [{service}] '{key_name}' 키를 찾을 수 없습니다")

    def _update_clock(self):
        self._clock.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        event.accept()


# ─────────────────────────────────────────
# 앱 실행 진입점
# ─────────────────────────────────────────
def launch_gui():
    app = QApplication(sys.argv)
    app.setStyleSheet(DARK_THEME)
    app.setApplicationName("API Key 자동화")
    app.setApplicationVersion("1.0.0")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    launch_gui()
