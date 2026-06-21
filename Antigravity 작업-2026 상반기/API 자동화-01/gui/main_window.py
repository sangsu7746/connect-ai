"""
MainWindow - API Key 자동화 프로그램 메인 창

디자인: GitHub Dark 팔레트 기반 모던 다크 테마
레이아웃:
  - 좌측 사이드패널: 서비스 선택 카드
  - 우측 메인패널: 실시간 로그 + 진행바
  - 하단: 상태바
"""

import sys
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote, unquote

from PyQt6.QtCore import Qt, QSize, QUrl, QTimer, pyqtSlot
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
