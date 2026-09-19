"""
dashboard.py
네블기(네이버 블로그 마스터) AI 에이전트 대시보드
"""
import threading
import logging
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk
from datetime import datetime

import config as cfg
from scheduler import BlogScheduler

# ── 색상 상수
BG_DARK    = "#1e1e2e"
BG_PANEL   = "#2a2a3e"
BG_INPUT   = "#313150"
BG_CARD    = "#252538"
FG_MAIN    = "#cdd6f4"
FG_DIM     = "#a6adc8"
ACCENT     = "#89b4fa"
ACCENT_GRN = "#a6e3a1"
ACCENT_YLW = "#f9e2af"
ACCENT_RED = "#f38ba8"

FONT_H1    = ("Malgun Gothic", 16, "bold")
FONT_H2    = ("Malgun Gothic", 11, "bold")
FONT_BODY  = ("Malgun Gothic", 10)
FONT_SMALL = ("Malgun Gothic", 9)
FONT_MONO  = ("Consolas", 9)

AGENT_LIST = [
    ("서치대리",  "🔎"),
    ("글작가",   "✍️"),
    ("이미지대리", "🎨"),
    ("편집과장",  "🗂️"),
    ("경리과장",  "🧮"),
]

THEMES = [
    "✨ 전문가 작성 (기본)", "💼 비즈니스", "🏃 운동건강", "🏠 일상라이프",
    "🧠 자기계발", "💰 재테크", "🛍️ 제품리뷰", "🎬 취미엔터", "📱 IT디지털",
]

ARTICLE_TYPES = [
    "📝 일반 포스팅 (기본)",
    "📋 TOP 5 비교 리스티클 (SEO/GEO 최적화)",
    "🏷️ 체험형 리뷰 (DIA+ 최적화)",
]


# ── 로그 핸들러: logging → Tkinter 콜백
class _TkLogHandler(logging.Handler):
    def __init__(self, callback):
        super().__init__()
        self._cb = callback
        self.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record):
        try:
            self._cb(self.format(record))
        except Exception:
            pass


# ── 메인 앱
class BlogiDashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("🤖 네블기 AI 마스터 대시보드")
        self.geometry("960x740")
        self.minsize(820, 620)
        self.configure(bg=BG_DARK)
        self.resizable(True, True)

        self._config = cfg.load_config()
        self._scheduler = BlogScheduler()
        self._orchestrator = None
        self._running = False

        # 에이전트 상태 변수 {이름: (상태라벨Var, 점라벨Var)}
        self._agent_vars: dict[str, tuple[tk.StringVar, tk.StringVar]] = {}

        # logging 연결
        self._log_handler = _TkLogHandler(self._append_log)
        logging.getLogger().addHandler(self._log_handler)
        logging.getLogger().setLevel(logging.INFO)

        self._build_header()
        self._build_notebook()
        self._build_status_bar()
        self._load_ui_from_config()
        self._update_scheduler_ui()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── 헤더
    def _build_header(self):
        hdr = tk.Frame(self, bg=BG_PANEL, pady=10)
        hdr.pack(fill="x", side="top")
        tk.Label(hdr, text="🤖  네블기 AI 마스터 대시보드",
                 bg=BG_PANEL, fg=ACCENT, font=FONT_H1).pack(side="left", padx=20)
        self._sched_badge = tk.Label(hdr, text="● 스케줄러 OFF",
                                     bg=BG_PANEL, fg=ACCENT_RED, font=FONT_SMALL)
        self._sched_badge.pack(side="right", padx=20)

    # ── 탭 컨테이너
    def _build_notebook(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("D.TNotebook", background=BG_DARK, borderwidth=0)
        style.configure("D.TNotebook.Tab", background=BG_PANEL, foreground=FG_DIM,
                         padding=[14, 6], font=FONT_H2)
        style.map("D.TNotebook.Tab",
                  background=[("selected", BG_INPUT)],
                  foreground=[("selected", ACCENT)])

        nb = ttk.Notebook(self, style="D.TNotebook")
        nb.pack(fill="both", expand=True, padx=10, pady=(5, 0))

        for title, builder in [
            ("⚙️  설정",          self._build_tab_settings),
            ("🚀  올인원 포스팅", self._build_tab_posting),
            ("🛍️  쿠팡 TOP100 릴스/위젯", self._build_tab_coupang),
            ("⏰  자동 스케줄러", self._build_tab_scheduler),
            ("📋  로그",          self._build_tab_log),
        ]:
            frame = tk.Frame(nb, bg=BG_DARK)
            nb.add(frame, text=title)
            builder(frame)

    # ── 탭 1: 설정
    def _build_tab_settings(self, parent):
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill="both", expand=True, padx=20, pady=15)

        def card(title):
            f = tk.LabelFrame(outer, text=f"  {title}  ", bg=BG_CARD, fg=ACCENT,
                              font=FONT_H2, bd=1, relief="flat", labelanchor="nw")
            f.pack(fill="x", pady=8)
            return f

        self._api_key_var  = self._row_entry(card("🔑 Gemini API 키"), "API 키", show="*")
        naver = card("🟢 네이버 계정")
        self._naver_id_var = self._row_entry(naver, "아이디")
        self._naver_pw_var = self._row_entry(naver, "비밀번호", show="*")
        self._naver_cat_var = self._row_entry(naver, "기본 카테고리 (선택)")

        opt = card("🖥️ 브라우저 옵션")
        self._headless_var = tk.BooleanVar()
        tk.Checkbutton(opt, text="헤드리스 모드 (창 숨기기)",
                       variable=self._headless_var,
                       bg=BG_CARD, fg=FG_MAIN, font=FONT_BODY,
                       selectcolor=BG_INPUT, activebackground=BG_CARD,
                       activeforeground=FG_MAIN).pack(anchor="w", padx=15, pady=8)

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", pady=6)
        self._btn(btn_row, "💾  설정 저장", self._save_settings, ACCENT).pack(side="right")

    # ── 탭 2: 올인원 포스팅
    def _build_tab_posting(self, parent):
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill="both", expand=True, padx=20, pady=15)

        # 입력 카드
        inp = tk.LabelFrame(outer, text="  📝 포스팅 설정  ", bg=BG_CARD, fg=ACCENT,
                            font=FONT_H2, bd=1, relief="flat")
        inp.pack(fill="x", pady=(0, 10))

        # 테마(분야) 선택을 먼저 배치하여 발제 시 참조할 수 있게 함.
        row_theme = tk.Frame(inp, bg=BG_CARD)
        row_theme.pack(fill="x", padx=15, pady=5)
        tk.Label(row_theme, text="블로그 분야(테마)", bg=BG_CARD, fg=FG_DIM,
                 font=FONT_BODY, width=18, anchor="w").pack(side="left")
        self._theme_var = tk.StringVar(value=THEMES[0])
        ttk.Combobox(row_theme, textvariable=self._theme_var, values=THEMES,
                     state="readonly", font=FONT_BODY).pack(side="left", fill="x", expand=True)
                     
        # 발제 대리 호출 버튼
        self._btn(row_theme, "💡 분야별 주제 자동 발제", self._on_topic_suggest, ACCENT_YLW).pack(side="right", padx=(10, 0))

        # 글 유형 선택
        row_type = tk.Frame(inp, bg=BG_CARD)
        row_type.pack(fill="x", padx=15, pady=5)
        tk.Label(row_type, text="글 유형", bg=BG_CARD, fg=FG_DIM,
                 font=FONT_BODY, width=20, anchor="w").pack(side="left")
        self._article_type_var = tk.StringVar(value=ARTICLE_TYPES[0])
        ttk.Combobox(row_type, textvariable=self._article_type_var, values=ARTICLE_TYPES,
                     state="readonly", font=FONT_BODY).pack(side="left", fill="x", expand=True)

        self._topic_var   = self._row_entry(inp, "블로그 주제 *")
        self._kw_var      = self._row_entry(inp, "키워드 (쉼표 구분)")
        self._tone_var    = self._row_entry(inp, "톤앤매너")
        self._tone_var.set("전문적이고 신뢰감 있게, 비유를 사용해 쉽게")
        
        self._brand_var   = self._row_entry(inp, "내 브랜드명 (비교글용)")

        # 에이전트 상태 카드
        agents_card = tk.LabelFrame(outer, text="  🤖 에이전트 파이프라인 현황  ",
                                    bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        agents_card.pack(fill="x", pady=(0, 10))

        row_agents = tk.Frame(agents_card, bg=BG_CARD)
        row_agents.pack(fill="x", padx=10, pady=10)

        for name, icon in AGENT_LIST:
            col = tk.Frame(row_agents, bg=BG_INPUT, padx=8, pady=8)
            col.pack(side="left", expand=True, fill="x", padx=4)

            dot_var   = tk.StringVar(value="⬜")
            label_var = tk.StringVar(value="대기")

            tk.Label(col, text=f"{icon} {name}", bg=BG_INPUT, fg=FG_MAIN,
                     font=FONT_SMALL).pack()
            tk.Label(col, textvariable=dot_var, bg=BG_INPUT, font=("Malgun Gothic", 14)).pack()
            tk.Label(col, textvariable=label_var, bg=BG_INPUT, fg=FG_DIM,
                     font=FONT_SMALL).pack()

            self._agent_vars[name] = (dot_var, label_var)

        # 실행 버튼
        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x")
        self._run_btn = self._btn(btn_row, "🚀  올인원 포스팅 시작", self._on_run, ACCENT_GRN)
        self._run_btn.pack(side="right")

    # ── 탭 3: 쿠팡 TOP 100 릴스/위젯
    def _build_tab_coupang(self, parent):
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill="both", expand=True, padx=15, pady=10)

        # 컨트롤 바
        ctrl = tk.LabelFrame(outer, text="  🛍️ 쿠팡 TOP 100 할인율 & 인기 상품 수집기  ",
                            bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        ctrl.pack(fill="x", pady=(0, 10))

        row_ctrl = tk.Frame(ctrl, bg=BG_CARD)
        row_ctrl.pack(fill="x", padx=15, pady=10)

        self._btn(row_ctrl, "🔎 TOP 100 수집 및 일별 가격 DB 갱신", self._on_crawl_coupang, ACCENT_GRN).pack(side="left")
        
        self._coupang_status_lbl = tk.Label(row_ctrl, text="상태: 수집 대기 중", bg=BG_CARD, fg=FG_DIM, font=FONT_BODY)
        self._coupang_status_lbl.pack(side="left", padx=15)

        self._widget_server_lbl = tk.Label(row_ctrl, text="🌐 위젯 서버: http://localhost:5050 가동 완료", bg=BG_CARD, fg=ACCENT_YLW, font=FONT_SMALL)
        self._widget_server_lbl.pack(side="right")

        # 테이블
        tbl_frame = tk.LabelFrame(outer, text="  📋 쿠팡 할인율 & 전날 가격 비교 목록 (상품 선택 후 아래 액션 실행)  ",
                                 bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        tbl_frame.pack(fill="both", expand=True, pady=(0, 10))

        style = ttk.Style()
        style.configure("Coupang.Treeview", background=BG_INPUT, foreground=FG_MAIN, fieldbackground=BG_INPUT, rowheight=26)
        style.map("Coupang.Treeview", background=[('selected', ACCENT)], foreground=[('selected', BG_DARK)])

        columns = ("rank", "id", "title", "cat", "curr_price", "orig_price", "disc", "diff")
        self._coupang_tree = ttk.Treeview(tbl_frame, columns=columns, show="headings", style="Coupang.Treeview")

        self._coupang_tree.heading("rank", text="순위")
        self._coupang_tree.heading("id", text="상품ID")
        self._coupang_tree.heading("title", text="상품명")
        self._coupang_tree.heading("cat", text="카테고리")
        self._coupang_tree.heading("curr_price", text="현재가")
        self._coupang_tree.heading("orig_price", text="정가")
        self._coupang_tree.heading("disc", text="할인율")
        self._coupang_tree.heading("diff", text="전일 대비 변동")

        self._coupang_tree.column("rank", width=45, anchor="center")
        self._coupang_tree.column("id", width=95, anchor="center")
        self._coupang_tree.column("title", width=320)
        self._coupang_tree.column("cat", width=90, anchor="center")
        self._coupang_tree.column("curr_price", width=90, anchor="e")
        self._coupang_tree.column("orig_price", width=90, anchor="e")
        self._coupang_tree.column("disc", width=65, anchor="center")
        self._coupang_tree.column("diff", width=150, anchor="center")

        vsb = ttk.Scrollbar(tbl_frame, orient="vertical", command=self._coupang_tree.yview)
        self._coupang_tree.configure(yscrollcommand=vsb.set)
        
        self._coupang_tree.pack(side="left", fill="both", expand=True, padx=(10,0), pady=10)
        vsb.pack(side="right", fill="y", padx=(0,10), pady=10)

        self._coupang_tree.bind("<<TreeviewSelect>>", self._on_coupang_select)

        # 액션 카드
        act_card = tk.LabelFrame(outer, text="  🎬 선택 상품 릴스 영상 제작 & 동적 차트 위젯 블로그 자동 포스팅  ",
                                bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        act_card.pack(fill="x")

        row_act = tk.Frame(act_card, bg=BG_CARD)
        row_act.pack(fill="x", padx=15, pady=10)

        self._sel_prod_var = tk.StringVar(value="선택된 상품: 목록에서 상품을 선택하세요")
        tk.Label(row_act, textvariable=self._sel_prod_var, bg=BG_CARD, fg=FG_MAIN, font=FONT_BODY).pack(side="left")

        act_btns = tk.Frame(row_act, bg=BG_CARD)
        act_btns.pack(side="right")

        self._btn(act_btns, "📊 가격 차트 위젯 미리보기", self._on_preview_widget, ACCENT_YLW).pack(side="left", padx=4)
        self._btn(act_btns, "🎬 부동산 릴스 영상 생성", self._on_generate_reels, ACCENT).pack(side="left", padx=4)
        self._btn(act_btns, "🚀 위젯+릴스 원클릭 포스팅", self._on_post_coupang_blog, ACCENT_GRN).pack(side="left", padx=4)

        # 서버 시작 및 목록 로드
        try:
            import price_widget_server as widget_server
            widget_server.start_widget_server()
        except Exception:
            pass
        self._refresh_coupang_tree()

    def _on_crawl_coupang(self):
        self._coupang_status_lbl.config(text="상위 100개 상품 수집 중...", fg=ACCENT_YLW)
        def task():
            try:
                import coupang_collector as collector
                prods = collector.crawl_coupang_top100()
                self.after(0, lambda: self._refresh_coupang_tree())
                self.after(0, lambda: self._coupang_status_lbl.config(text=f"완료 ({len(prods)}개 상품 갱신)", fg=ACCENT_GRN))
                self.after(0, lambda: self._log(f"🛍️ 쿠팡 TOP 100 상품 수집 완료 ({len(prods)}개)"))
            except Exception as e:
                self.after(0, lambda: self._coupang_status_lbl.config(text=f"오류: {e}", fg=ACCENT_RED))
        threading.Thread(target=task, daemon=True).start()

    def _refresh_coupang_tree(self):
        try:
            import coupang_collector as collector
            for item in self._coupang_tree.get_children():
                self._coupang_tree.delete(item)
            prods = collector.get_all_products_from_db()
            for p in prods:
                comp = p.get("comparison", {})
                diff_str = "➡️ 동일"
                if comp.get("status") == "down":
                    diff_str = f"📉 -{abs(comp.get('diff', 0)):,}원"
                elif comp.get("status") == "up":
                    diff_str = f"📈 +{abs(comp.get('diff', 0)):,}원"
                    
                self._coupang_tree.insert("", "end", values=(
                    f"{p.get('rank_num', 0)}위",
                    p.get("product_id"),
                    p.get("title", ""),
                    p.get("category", "기타"),
                    f"{p.get('current_price', 0):,}원",
                    f"{p.get('original_price', 0):,}원",
                    f"{p.get('discount_rate', 0)}%",
                    diff_str
                ))
            if prods:
                self._coupang_status_lbl.config(text=f"DB 등록 상품: 총 {len(prods)}개", fg=ACCENT_GRN)
        except Exception as e:
            print(f"[UI Tree Error] {e}")

    def _get_selected_product_id(self):
        sel = self._coupang_tree.selection()
        if not sel:
            return None
        item = self._coupang_tree.item(sel[0])
        return item["values"][1]

    def _on_coupang_select(self, event):
        pid = self._get_selected_product_id()
        if pid:
            import coupang_collector as collector
            prods = collector.get_all_products_from_db()
            p = next((x for x in prods if x["product_id"] == pid), None)
            if p:
                title = p['title'] if len(p['title']) <= 25 else p['title'][:25] + "..."
                self._sel_prod_var.set(f"선택: [{p['product_id']}] {title} ({p['current_price']:,}원)")

    def _on_preview_widget(self):
        pid = self._get_selected_product_id()
        if not pid:
            messagebox.showwarning("선택 오류", "가격 그래프 위젯을 확인할 상품을 목록에서 선택해주세요.")
            return
        try:
            import price_widget_server as widget_server
            chart_path = widget_server.save_widget_chart_image(pid)
            self._log(f"📊 가격변동 차트 생성 완료: {chart_path}")
            
            dlg = tk.Toplevel(self)
            dlg.title(f"📊 동적 가격 변동 위젯 차트 미리보기 ({pid})")
            dlg.geometry("840x500")
            dlg.configure(bg=BG_DARK)
            
            from PIL import ImageTk, Image
            img = Image.open(chart_path)
            img = img.resize((800, 420), Image.Resampling.LANCZOS)
            photo = ImageTk.PhotoImage(img)
            
            lbl = tk.Label(dlg, image=photo, bg=BG_DARK)
            lbl.image = photo
            lbl.pack(padx=20, pady=20)
        except Exception as e:
            messagebox.showerror("차트 오류", f"위젯 차트 생성 중 오류: {e}")

    def _on_generate_reels(self):
        pid = self._get_selected_product_id()
        if not pid:
            messagebox.showwarning("선택 오류", "릴스 영상을 생성할 상품을 목록에서 선택해주세요.")
            return
        self._log(f"🎬 부동산 스타일 릴스 영상 생성 시작 ({pid})...")
        def task():
            try:
                import reels_generator as reels
                path = reels.generate_product_reels_video(pid)
                self.after(0, lambda: self._log(f"🎉 릴스 영상 생성 완료: {path}"))
                self.after(0, lambda: messagebox.showinfo("릴스 생성 완료", f"부동산 스타일 릴스 영상이 생성되었습니다!\n저장 경로: {path}"))
            except Exception as e:
                self.after(0, lambda: self._log(f"❌ 릴스 영상 생성 실패: {e}"))
                self.after(0, lambda: messagebox.showerror("릴스 생성 오류", str(e)))
        threading.Thread(target=task, daemon=True).start()

    def _on_post_coupang_blog(self):
        pid = self._get_selected_product_id()
        if not pid:
            messagebox.showwarning("선택 오류", "블로그 포스팅을 진행할 상품을 목록에서 선택해주세요.")
            return
        if not messagebox.askyesno("블로그 포스팅 실행", f"선택한 상품({pid})으로 AI 릴스 + 동적 가격 위젯 + 네이버 블로그 포스팅을 실행할까요?"):
            return
            
        self._set_running(True)
        self._log(f"🚀 쿠팡 원클릭 자동 포스팅 파이프라인 가동 ({pid})...")
        def task():
            try:
                import coupang_blog_pipeline as pipeline
                res = pipeline.run_coupang_pipeline(pid, logger_func=self._log)
                if res.get("status") == "success":
                    self.after(0, lambda: messagebox.showinfo("포스팅 완료", "네이버 블로그 포스팅이 성공적으로 등록되었습니다!"))
                elif res.get("status") == "prepared":
                    self.after(0, lambda: messagebox.showinfo("원고/첨부 준비 완료", "원고, 차트 위젯, 릴스 영상 생성이 완료되었습니다.\n네이버 계정을 설정에서 등록하면 자동 포스팅됩니다."))
            except Exception as e:
                self.after(0, lambda: self._log(f"❌ 파이프라인 오류: {e}"))
                self.after(0, lambda: messagebox.showerror("포스팅 오류", str(e)))
            finally:
                self.after(0, lambda: self._set_running(False))
        threading.Thread(target=task, daemon=True).start()

    # ── 탭 4: 스케줄러
    def _build_tab_scheduler(self, parent):
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill="both", expand=True, padx=20, pady=15)

        sched = tk.LabelFrame(outer, text="  ⏰ 자동 포스팅 스케줄  ",
                              bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        sched.pack(fill="x")

        self._sched_enabled_var = tk.BooleanVar()
        tk.Checkbutton(sched, text="자동 스케줄러 활성화",
                       variable=self._sched_enabled_var,
                       command=self._toggle_scheduler,
                       bg=BG_CARD, fg=FG_MAIN, font=FONT_H2,
                       selectcolor=BG_INPUT, activebackground=BG_CARD,
                       activeforeground=FG_MAIN).pack(anchor="w", padx=15, pady=10)

        self._sched_time_var    = self._row_entry(sched, "포스팅 시간 (HH:MM)")
        self._sched_topic_var   = self._row_entry(sched, "주제")
        self._sched_kw_var      = self._row_entry(sched, "키워드")
        self._sched_tone_var    = self._row_entry(sched, "톤앤매너")

        btn_row = tk.Frame(sched, bg=BG_CARD)
        btn_row.pack(fill="x", padx=15, pady=10)
        self._btn(btn_row, "💾 스케줄 저장", self._save_scheduler, ACCENT).pack(side="left", padx=(0, 8))
        self._btn(btn_row, "▶ 지금 즉시 실행", self._run_scheduler_now, ACCENT_GRN).pack(side="left")

        status_card = tk.LabelFrame(outer, text="  📊 스케줄러 상태  ",
                                    bg=BG_CARD, fg=ACCENT, font=FONT_H2, bd=1, relief="flat")
        status_card.pack(fill="x", pady=15)
        self._sched_status_lbl = tk.Label(status_card, text="스케줄러 꺼짐",
                                          bg=BG_CARD, fg=FG_DIM, font=FONT_BODY)
        self._sched_status_lbl.pack(pady=6)
        self._next_run_lbl = tk.Label(status_card, text="다음 실행: 미설정",
                                      bg=BG_CARD, fg=FG_DIM, font=FONT_SMALL)
        self._next_run_lbl.pack(pady=(0, 10))

    # ── 탭 4: 로그
    def _build_tab_log(self, parent):
        outer = tk.Frame(parent, bg=BG_DARK)
        outer.pack(fill="both", expand=True, padx=10, pady=10)

        self._log_text = scrolledtext.ScrolledText(
            outer, bg=BG_INPUT, fg=ACCENT_GRN,
            font=FONT_MONO, relief="flat", wrap="word", state="disabled")
        self._log_text.pack(fill="both", expand=True)

        btn_row = tk.Frame(outer, bg=BG_DARK)
        btn_row.pack(fill="x", pady=(5, 0))
        self._btn(btn_row, "🗑️ 로그 지우기", self._clear_log, ACCENT_RED).pack(side="right")

    # ── 상태바
    def _build_status_bar(self):
        bar = tk.Frame(self, bg=BG_PANEL, height=24)
        bar.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="준비")
        tk.Label(bar, textvariable=self._status_var,
                 bg=BG_PANEL, fg=FG_DIM, font=FONT_SMALL).pack(side="left", padx=10, pady=3)

    # ── 공통 위젯 생성
    def _row_entry(self, parent, label: str, show: str = "") -> tk.StringVar:
        row = tk.Frame(parent, bg=BG_CARD)
        row.pack(fill="x", padx=15, pady=5)
        tk.Label(row, text=label, bg=BG_CARD, fg=FG_DIM,
                 font=FONT_BODY, width=20, anchor="w").pack(side="left")
        var = tk.StringVar()
        tk.Entry(row, textvariable=var, bg=BG_INPUT, fg=FG_MAIN,
                 insertbackground=FG_MAIN, relief="flat",
                 font=FONT_BODY, show=show).pack(side="left", fill="x", expand=True, ipady=4)
        return var

    def _btn(self, parent, text, cmd, color=ACCENT) -> tk.Button:
        return tk.Button(parent, text=text, command=cmd,
                         bg=color, fg=BG_DARK, font=FONT_BODY,
                         relief="flat", cursor="hand2", padx=12, pady=5,
                         activebackground=FG_MAIN, activeforeground=BG_DARK)

    # ── 설정 로드 / 저장
    def _load_ui_from_config(self):
        c = self._config
        self._api_key_var.set(c.get("gemini_api_key", ""))
        self._naver_id_var.set(c.get("naver_id", ""))
        self._naver_pw_var.set(c.get("naver_pw", ""))
        self._naver_cat_var.set(c.get("default_category", ""))
        self._headless_var.set(c.get("headless_mode", False))
        self._topic_var.set(c.get("default_topic", ""))
        self._kw_var.set(c.get("default_keywords", ""))
        self._sched_time_var.set(c.get("schedule_time", "09:00"))
        self._sched_topic_var.set(c.get("schedule_topic", ""))
        self._sched_kw_var.set(c.get("schedule_keywords", ""))
        self._sched_enabled_var.set(c.get("schedule_enabled", False))
        if c.get("schedule_enabled"):
            self._start_scheduler()

    def _save_settings(self):
        self._config.update({
            "gemini_api_key":   self._api_key_var.get().strip(),
            "naver_id":         self._naver_id_var.get().strip(),
            "naver_pw":         self._naver_pw_var.get().strip(),
            "default_category": self._naver_cat_var.get().strip(),
            "headless_mode":    self._headless_var.get(),
            "default_topic":    self._topic_var.get().strip(),
            "default_keywords": self._kw_var.get().strip(),
        })
        cfg.save_config(self._config)
        self._log("✅ 설정 저장 완료")
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")

    # ── 발제 대리 실행 (스레드)
    def _on_topic_suggest(self):
        category = self._theme_var.get()
        if not category:
            messagebox.showwarning("입력 오류", "블로그 분야(테마)를 먼저 선택해주세요.")
            return
            
        if not self._api_key_var.get().strip():
            messagebox.showwarning("입력 오류", "설정 탭에서 Gemini API 키를 먼저 입력해주세요.")
            return
            
        self._set_running(True)
        self._log(f"💡 '{category}' 분야 발제(트렌드 분석) 시작...")
        
        def task():
            try:
                self._save_settings_silent()
                from agents.agent_topic import AgentTopic
                topic_agent = AgentTopic()
                result = topic_agent.execute(category)
                
                if result.get("status") == "success":
                    self.after(0, lambda: self._show_topic_popup(result["topics"]))
                else:
                    self.after(0, lambda: messagebox.showerror("발제 오류", result.get("error", "알 수 없는 오류")))
            except Exception as e:
                self.after(0, lambda: self._log(f"❌ 발제 중 오류 발생: {e}"))
                self.after(0, lambda: messagebox.showerror("오류", str(e)))
            finally:
                self.after(0, lambda: self._set_running(False))
                
        threading.Thread(target=task, daemon=True).start()

    def _show_topic_popup(self, topics):
        dlg = tk.Toplevel(self)
        dlg.title("💡 발제 대리 추천 (Top 5 핫이슈 트렌드)")
        dlg.geometry("800x400")
        dlg.configure(bg=BG_DARK)
        dlg.transient(self)
        dlg.grab_set()

        tk.Label(dlg, text="아래 트렌드 주제 중 하나를 더블클릭하면 글 주제로 자동 설정됩니다.",
                 bg=BG_DARK, fg=FG_MAIN, font=FONT_BODY).pack(pady=(10, 4))
                 
        # Treeview 스타일
        style = ttk.Style(dlg)
        style.theme_use("clam")
        style.configure("Topic.Treeview", background=BG_INPUT, foreground=FG_MAIN, fieldbackground=BG_INPUT, rowheight=30)
        style.map("Topic.Treeview", background=[('selected', ACCENT)], foreground=[('selected', BG_DARK)])
                 
        tree = ttk.Treeview(dlg, columns=("rank", "keyword", "title", "reason"), show="headings", style="Topic.Treeview")
        tree.heading("rank", text="순위")
        tree.heading("keyword", text="메인 키워드")
        tree.heading("title", text="추천 포스팅 제목")
        tree.heading("reason", text="선정 이유")
        
        tree.column("rank", width=50, anchor="center")
        tree.column("keyword", width=120)
        tree.column("title", width=250)
        tree.column("reason", width=340)
        
        for t in topics:
            tree.insert("", "end", values=(
                f"{t.get('rank', '-')}위",
                t.get("keyword", ""),
                t.get("recommended_title", ""),
                t.get("reason", "")
            ))
            
        tree.pack(fill="both", expand=True, padx=20, pady=10)
        
        def on_double_click(event):
            sel = tree.selection()
            if not sel:
                return
            item = tree.item(sel[0])
            vals = item["values"]
            title = vals[2]
            kw = vals[1]
            
            # UI 변수 업데이트
            self._topic_var.set(title)
            self._kw_var.set(kw)
            
            self._log(f"💡 발제 적용 완료: {title}")
            dlg.destroy()
            
        tree.bind("<Double-1>", on_double_click)
        
        tk.Button(dlg, text="닫기", command=dlg.destroy,
                  bg=BG_CARD, fg=FG_DIM, font=FONT_BODY, relief="flat", padx=12
                  ).pack(pady=10)

    # ── 포스팅 실행
    def _on_run(self):
        topic = self._topic_var.get().strip()
        if not topic:
            messagebox.showwarning("입력 오류", "블로그 주제를 입력해주세요.")
            return
        if not self._api_key_var.get().strip():
            messagebox.showwarning("입력 오류", "설정 탭에서 Gemini API 키를 먼저 입력해주세요.")
            return
        if not messagebox.askyesno("포스팅 시작",
                                   f"'{topic}' 주제로 AI 포스팅을 시작할까요?\n(1~3분 소요)"):
            return

        self._reset_agent_status()
        self._set_running(True)
        threading.Thread(target=self._run_pipeline, daemon=True).start()

    def _run_pipeline(self):
        try:
            self._save_settings_silent()
            from agents.orchestrator import MasterOrchestrator
            orc = MasterOrchestrator()

            result = orc.run_daily_posting(
                topic=self._topic_var.get().strip(),
                keywords=self._kw_var.get().strip(),
                tone_and_manner=self._tone_var.get().strip(),
                theme_name=self._theme_var.get(),
                article_type=self._article_type_var.get(),
                brand_name=self._brand_var.get().strip(),
                progress_callback=self._on_agent_progress,
                desking_callback=self._on_desking,
            )

            if result:
                self.after(0, lambda: messagebox.showinfo("완료", "✅ 네이버 블로그 포스팅까지 완료되었습니다!"))
            else:
                self.after(0, lambda: self._log("⚠️ 파이프라인이 중간에 중단되었습니다. (취소 또는 오류)"))
        except Exception as e:
            self.after(0, lambda: self._log(f"❌ 오류 발생: {e}"))
            self.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.after(0, lambda: self._set_running(False))

    def _save_settings_silent(self):
        self._config.update({
            "gemini_api_key":   self._api_key_var.get().strip(),
            "naver_id":         self._naver_id_var.get().strip(),
            "naver_pw":         self._naver_pw_var.get().strip(),
            "default_category": self._naver_cat_var.get().strip(),
            "headless_mode":    self._headless_var.get(),
        })
        cfg.save_config(self._config)

    # ── 에이전트 진행 상태 콜백
    def _on_agent_progress(self, agent_name: str, status: str):
        def _update():
            if agent_name not in self._agent_vars:
                return
            dot_var, label_var = self._agent_vars[agent_name]
            if status == "running":
                dot_var.set("🔄")
                label_var.set("실행 중")
            elif status == "done":
                dot_var.set("✅")
                label_var.set("완료")
            elif status == "error":
                dot_var.set("❌")
                label_var.set("오류")
        self.after(0, _update)

    def _reset_agent_status(self):
        for dot_var, label_var in self._agent_vars.values():
            dot_var.set("⬜")
            label_var.set("대기")

    # ── 편집장 데스킹 팝업 (백그라운드 스레드에서 호출됨)
    # 반환: {"title":str, "content":str, "tags":str, "image_paths":list} 또는 None(취소)
    def _on_desking(self, editor_res: dict, full_content: str):
        done_event = threading.Event()
        result = {"data": None}

        def _show_popup():
            dlg = tk.Toplevel(self)
            dlg.title("📋 편집장 데스킹 — 최종 결재 및 이미지 첨부")
            dlg.geometry("1000x760")
            dlg.configure(bg=BG_DARK)
            dlg.transient(self)
            dlg.grab_set()

            tk.Label(dlg, text="원고·이미지를 확인·수정한 뒤 승인(포스팅) 또는 취소를 선택하세요.",
                     bg=BG_DARK, fg=FG_MAIN, font=FONT_BODY).pack(pady=(10, 4))

            # 제목
            tk.Label(dlg, text="제목", bg=BG_DARK, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", padx=20)
            title_var = tk.StringVar(value=editor_res.get("final_title", ""))
            tk.Entry(dlg, textvariable=title_var, font=FONT_BODY,
                     bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                     relief="flat").pack(fill="x", padx=20, pady=(2, 6), ipady=4)

            # 키워드
            tk.Label(dlg, text="키워드/태그 (쉼표 구분)", bg=BG_DARK, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w", padx=20)
            tags_var = tk.StringVar(value=editor_res.get("tags", ""))
            tk.Entry(dlg, textvariable=tags_var, font=FONT_BODY,
                     bg=BG_INPUT, fg=FG_MAIN, insertbackground=FG_MAIN,
                     relief="flat").pack(fill="x", padx=20, pady=(2, 6), ipady=4)

            # 하단 버튼 (잘림 방지: 먼저 pack)
            btn_frame = tk.Frame(dlg, bg=BG_DARK)
            btn_frame.pack(side="bottom", fill="x", pady=10)

            # 본문 + 이미지 좌우 분할
            split = tk.Frame(dlg, bg=BG_DARK)
            split.pack(fill="both", expand=True, padx=20, pady=(4, 6))

            # ─ 좌측: 본문 편집기
            tk.Label(split, text="본문 (수정 가능)", bg=BG_DARK, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")
            content_box = scrolledtext.ScrolledText(
                split, font=FONT_BODY, bg=BG_INPUT, fg=FG_MAIN,
                wrap="word", insertbackground=FG_MAIN, relief="flat", width=60)
            content_box.pack(side="left", fill="both", expand=True, padx=(0, 10))
            content_box.insert("1.0", full_content)

            # ─ 우측: 이미지 리스트
            img_panel = tk.Frame(split, bg=BG_DARK, width=260)
            img_panel.pack(side="right", fill="y")
            img_panel.pack_propagate(False)

            tk.Label(img_panel, text="첨부 이미지 목록", bg=BG_DARK, fg=FG_DIM, font=FONT_SMALL).pack(anchor="w")

            # 이미지 추가/삭제 버튼 (먼저 pack)
            img_btn_row = tk.Frame(img_panel, bg=BG_DARK)
            img_btn_row.pack(side="bottom", fill="x", pady=(4, 0))

            # 썸네일 미리보기 캔버스
            preview_canvas = tk.Canvas(img_panel, bg=BG_INPUT, height=160, highlightthickness=0)
            preview_canvas.pack(side="bottom", fill="x", pady=(4, 0))
            tk.Label(preview_canvas, text="[이미지 미리보기]",
                     bg=BG_INPUT, fg=FG_DIM, font=FONT_SMALL).place(relx=0.5, rely=0.5, anchor="center")
            preview_canvas.image_ref = None

            # 리스트박스
            img_listbox = tk.Listbox(img_panel, bg=BG_INPUT, fg=FG_MAIN,
                                     selectbackground=ACCENT, font=FONT_SMALL)
            img_listbox.pack(fill="both", expand=True, pady=(4, 0))

            # 에이전트가 제안한 이미지 경로 자동 추가
            for p in editor_res.get("image_paths", []):
                img_listbox.insert("end", p)

            def _show_preview(event=None):
                sel = img_listbox.curselection()
                if not sel:
                    return
                path = img_listbox.get(sel[0])
                try:
                    import os
                    from PIL import Image, ImageTk
                    if os.path.exists(path):
                        img = Image.open(path)
                        img.thumbnail((240, 160), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(img)
                        preview_canvas.delete("all")
                        preview_canvas.create_image(120, 0, anchor="n", image=photo)
                        preview_canvas.image_ref = photo
                except Exception:
                    pass

            img_listbox.bind("<<ListboxSelect>>", _show_preview)

            def _add_images():
                from tkinter import filedialog
                files = filedialog.askopenfilenames(
                    title="첨부할 이미지 선택",
                    filetypes=[("이미지", "*.png *.jpg *.jpeg *.gif *.webp")])
                for f in files:
                    img_listbox.insert("end", f)

            def _del_image():
                sel = img_listbox.curselection()
                if sel:
                    for i in reversed(sel):
                        img_listbox.delete(i)
                    preview_canvas.delete("all")
                    tk.Label(preview_canvas, text="[이미지 미리보기]",
                             bg=BG_INPUT, fg=FG_DIM, font=FONT_SMALL).place(relx=0.5, rely=0.5, anchor="center")

            tk.Button(img_btn_row, text="➕ 이미지 추가", command=_add_images,
                      bg=BG_INPUT, fg=FG_MAIN, relief="flat", font=FONT_SMALL
                      ).pack(side="left", expand=True, fill="x", padx=(0, 2))
            tk.Button(img_btn_row, text="🗑️ 삭제", command=_del_image,
                      bg=ACCENT_RED, fg=BG_DARK, relief="flat", font=FONT_SMALL
                      ).pack(side="right", expand=True, fill="x", padx=(2, 0))

            def on_approve():
                result["data"] = {
                    "title":       title_var.get().strip(),
                    "content":     content_box.get("1.0", "end-1c"),
                    "tags":        tags_var.get().strip(),
                    "image_paths": list(img_listbox.get(0, "end")),
                }
                dlg.destroy()
                done_event.set()

            def on_cancel():
                dlg.destroy()
                done_event.set()

            dlg.protocol("WM_DELETE_WINDOW", on_cancel)

            tk.Button(btn_frame, text="취소 (포스팅 안 함)", command=on_cancel,
                      bg=BG_INPUT, fg=FG_MAIN, font=FONT_BODY, relief="flat", padx=12
                      ).pack(side="right", padx=20)
            tk.Button(btn_frame, text="✅ 승인 → 네이버 블로그 포스팅", command=on_approve,
                      bg=ACCENT_GRN, fg=BG_DARK, font=FONT_BODY, relief="flat", padx=12
                      ).pack(side="right")

        self.after(0, _show_popup)
        done_event.wait()
        return result["data"]

    # ── 로그 출력
    def _append_log(self, msg: str):
        def _do():
            self._log_text.configure(state="normal")
            self._log_text.insert("end", msg + "\n")
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
            self._status_var.set(msg[:90])
        self.after(0, _do)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self._append_log(f"{ts}  {msg}")

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _set_running(self, running: bool):
        self._running = running
        state = "disabled" if running else "normal"
        self._run_btn.configure(state=state)
        self._status_var.set("⚙️ 파이프라인 실행 중..." if running else "준비")

    # ── 스케줄러
    def _toggle_scheduler(self):
        if self._sched_enabled_var.get():
            self._start_scheduler()
        else:
            self._scheduler.stop()
            self._update_scheduler_ui()
            self._log("⏹ 스케줄러 중지됨")

    def _save_scheduler(self):
        self._config.update({
            "schedule_enabled":  self._sched_enabled_var.get(),
            "schedule_time":     self._sched_time_var.get().strip(),
            "schedule_topic":    self._sched_topic_var.get().strip(),
            "schedule_keywords": self._sched_kw_var.get().strip(),
        })
        cfg.save_config(self._config)
        if self._sched_enabled_var.get():
            self._start_scheduler()
        self._log("✅ 스케줄 설정 저장 완료")
        messagebox.showinfo("저장", "스케줄 설정이 저장되었습니다.")

    def _start_scheduler(self):
        post_time = self._sched_time_var.get().strip() or "09:00"
        self._scheduler.start(post_time, self._scheduled_job)
        self._update_scheduler_ui()
        self._log(f"▶ 스케줄러 시작: 매일 {post_time} 자동 포스팅")

    def _scheduled_job(self):
        topic = self._sched_topic_var.get().strip() or self._topic_var.get().strip()
        kw    = self._sched_kw_var.get().strip()    or self._kw_var.get().strip()
        if not topic:
            self._log("⚠️ 스케줄 실행 실패: 주제가 설정되지 않았습니다.")
            return
        self._reset_agent_status()
        self._set_running(True)

        def task():
            try:
                from agents.orchestrator import MasterOrchestrator
                orc = MasterOrchestrator()
                orc.run_daily_posting(
                    topic=topic, keywords=kw,
                    tone_and_manner=self._sched_tone_var.get().strip() or "전문적으로",
                    theme_name=self._theme_var.get(),
                    article_type=self._article_type_var.get(),
                    brand_name=self._brand_var.get().strip(),
                    progress_callback=self._on_agent_progress,
                    desking_callback=self._on_desking,
                )
            except Exception as e:
                self.after(0, lambda: self._log(f"❌ 스케줄 포스팅 오류: {e}"))
            finally:
                self.after(0, lambda: self._set_running(False))

        threading.Thread(target=task, daemon=True).start()

    def _run_scheduler_now(self):
        self._scheduler.run_now()

    def _update_scheduler_ui(self):
        if self._scheduler.is_running:
            next_run = self._scheduler.next_run_time()
            self._sched_status_lbl.configure(text="⏰ 스케줄러 실행 중", fg=ACCENT_GRN)
            self._next_run_lbl.configure(text=f"다음 실행: {next_run}")
            self._sched_badge.configure(text="● 스케줄러 ON", fg=ACCENT_GRN)
        else:
            self._sched_status_lbl.configure(text="⏹ 스케줄러 꺼짐", fg=ACCENT_RED)
            self._next_run_lbl.configure(text="다음 실행: 미설정")
            self._sched_badge.configure(text="● 스케줄러 OFF", fg=ACCENT_RED)
        self.after(3000, self._update_scheduler_ui)

    # ── 종료
    def _on_close(self):
        self._scheduler.stop()
        logging.getLogger().removeHandler(self._log_handler)
        self.destroy()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    app = BlogiDashboard()
    app.mainloop()
