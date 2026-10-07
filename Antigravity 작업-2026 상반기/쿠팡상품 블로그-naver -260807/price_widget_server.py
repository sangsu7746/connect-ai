"""
price_widget_server.py
매일 가격 변동 및 할인율 비교 동적 그래프 위젯 서버 & 차트 이미지 생성 모듈
"""
import os
import io
import sqlite3
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont
import coupang_collector as collector

# 추이 그래프를 그리기 위한 최소 관측 점수.
# 2점짜리 꺾은선은 '추이'가 아니라 두 값을 이은 선일 뿐인데, 그림이 되면 추세처럼 읽힌다.
# (2026-08-13 기준 실측 상품 79개 중 44개가 2점, 35개가 1점이다)
MIN_POINTS_FOR_CHART = 3

# Matplotlib 로드 시도
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    HAS_MATPLOTLIB = True
except Exception:
    HAS_MATPLOTLIB = False

# Flask 로드 시도
try:
    from flask import Flask, send_file, render_template_string, jsonify
    HAS_FLASK = True
except Exception:
    HAS_FLASK = False

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "temp_images")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def setup_korean_font():
    """Matplotlib 한글 폰트 설정 (Windows 맑은 고딕 기본)"""
    if not HAS_MATPLOTLIB:
        return
    font_path = "C:/Windows/Fonts/malgun.ttf"
    if os.path.exists(font_path):
        font_name = fm.FontProperties(fname=font_path).get_name()
        plt.rc('font', family=font_name)
    plt.rc('axes', unicode_minus=False)

def render_chart_with_matplotlib(product_info: dict, history_data: list) -> bytes:
    """Matplotlib을 사용해 세련된 매일 가격변동 그래프 차트 이미지를 생성합니다."""
    setup_korean_font()
    
    fig, ax = plt.subplots(figsize=(8.5, 4.8), dpi=120)
    fig.patch.set_facecolor('#1e1e2e')  # 다크 모드 프리미엄 배경
    ax.set_facecolor('#252538')
    
    dates = [h["date"][5:] for h in history_data] # MM-DD
    prices = [h["price"] for h in history_data]
    
    # 그래프 선 및 데이터 포인트
    ax.plot(dates, prices, color='#89b4fa', linewidth=2.5, marker='o', markersize=6, markerfacecolor='#f9e2af', markeredgecolor='#89b4fa')
    ax.fill_between(dates, prices, min(prices) * 0.95, color='#89b4fa', alpha=0.15)
    
    # 격자 및 축 설정
    ax.grid(True, linestyle='--', alpha=0.25, color='#a6adc8')
    ax.tick_params(colors='#cdd6f4', labelsize=9)
    for spine in ax.spines.values():
        spine.set_color('#313150')
        
    # Y축 레이블 포맷
    #
    # 기존에는 x >= 10000 이면 무조건 int(x/10000)만원 이었다.
    # 18,080원 ~ 18,670원 처럼 값 폭이 좁으면 눈금이 전부 "1만원" 으로 뭉개져
    # 축이 아무 정보도 주지 못했다(실제로 8칸 전부 '1만원'이었다).
    # 값의 폭을 보고 단위를 정한다.
    import matplotlib.ticker as ticker
    _span = (max(prices) - min(prices)) if prices else 0

    def price_formatter(x, pos):
        if _span >= 100000:                 # 폭이 아주 넓을 때만 만원 단위로 줄인다
            return f'{x / 10000:.0f}만원'
        if _span >= 20000:
            return f'{x / 10000:.1f}만원'
        return f'{int(round(x)):,}원'       # 좁으면 원 단위 그대로 보여준다

    ax.yaxis.set_major_formatter(ticker.FuncFormatter(price_formatter))
    # 눈금이 너무 촘촘하면 같은 값이 반복돼 보인다
    ax.yaxis.set_major_locator(ticker.MaxNLocator(nbins=5, integer=True))
    
    # 타이틀 및 변동 정보 박스
    title = product_info.get('title', '상품 가격 변동 추이')
    if len(title) > 28:
        title = title[:28] + "..."
        
    curr_price = product_info.get('current_price', 0)
    orig_price = product_info.get('original_price', 0)
    disc_rate = product_info.get('discount_rate', 0)
    comp = product_info.get('comparison', {})
    
    status_text = "전날과 동일"
    if comp.get("status") == "down":
        status_text = f"전날 대비 -{abs(comp.get('diff', 0)):,}원 (추가 할인!)"
    elif comp.get("status") == "up":
        status_text = f"전날 대비 +{abs(comp.get('diff', 0)):,}원"
        
    plt.suptitle(f"[쿠팡 파트너스 가격 추이] {title}", fontsize=12, fontweight='bold', color='#cdd6f4', y=0.96)
    ax.set_title(f"현재가: {curr_price:,}원 ({disc_rate}%↓) | 어제: {comp.get('yesterday_price', 0):,}원 | {status_text}", 
                 fontsize=10, color='#a6e3a1', pad=10)
    
    # 관측 구간의 최소값을 표시한다. '최저가'라고 부르지 않는다 —
    # 며칠치 관측의 최소값일 뿐, 그 상품의 역대 최저가인지는 알 수 없다.
    min_price = min(prices)
    min_idx = prices.index(min_price)
    ax.annotate(f'관측 최저\n{min_price:,}원',
                xy=(dates[min_idx], min_price),
                xytext=(dates[min_idx], min_price * 1.03),
                arrowprops=dict(facecolor='#f38ba8', shrink=0.08, width=1, headwidth=5),
                fontsize=9, color='#f38ba8', fontweight='bold', ha='center')
    
    plt.tight_layout()
    plt.subplots_adjust(top=0.85)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return buf.getvalue()

def render_chart_fallback_pillow(product_info: dict, history_data: list) -> bytes:
    """Matplotlib 미설치 시 Pillow를 사용하여 깔끔한 차트 이미지를 생성합니다."""
    width, height = 800, 420
    img = Image.new("RGB", (width, height), color="#1e1e2e")
    draw = ImageDraw.Draw(img)
    
    try:
        font_title = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 16)
        font_sub = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 13)
        font_small = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 11)
    except:
        font_title = font_sub = font_small = ImageFont.load_default()
        
    # 헤더 배경 바
    draw.rectangle([(0, 0), (width, 80)], fill="#2a2a3e")
    
    title = product_info.get("title", "")
    if len(title) > 32:
        title = title[:32] + "..."
    curr_price = product_info.get("current_price", 0)
    disc_rate = product_info.get("discount_rate", 0)
    comp = product_info.get("comparison", {})
    
    draw.text((20, 15), f"📊 [쿠팡 가격 추이] {title}", fill="#cdd6f4", font=font_title)
    
    status_str = f"오늘가: {curr_price:,}원 ({disc_rate}%↓) | 어제: {comp.get('yesterday_price',0):,}원"
    if comp.get("status") == "down":
        status_str += f" | 📉 전일대비 -{abs(comp.get('diff',0)):,}원 하락!"
    draw.text((20, 48), status_str, fill="#a6e3a1", font=font_sub)
    
    # 꺾은선 그래프 영역
    gx, gy, gw, gh = 60, 110, 700, 260
    draw.rectangle([(gx, gy), (gx + gw, gy + gh)], fill="#252538", outline="#313150", width=1)
    
    prices = [h["price"] for h in history_data]
    dates = [h["date"][5:] for h in history_data]
    
    min_p, max_p = min(prices), max(prices)
    if min_p == max_p:
        min_p = int(max_p * 0.9)
        max_p = int(max_p * 1.1)
        
    points = []
    n = len(prices)
    for i in range(n):
        px = gx + int((i / max(1, n - 1)) * gw)
        py = gy + gh - int(((prices[i] - min_p) / max(1, max_p - min_p)) * (gh - 40)) - 20
        points.append((px, py))
        # 데이터 점
        draw.ellipse([(px - 4, py - 4), (px + 4, py + 4)], fill="#f9e2af", outline="#89b4fa", width=2)
        # 날짜 레이블
        draw.text((px - 15, gy + gh + 5), dates[i], fill="#a6adc8", font=font_small)
        
    if len(points) > 1:
        draw.line(points, fill="#89b4fa", width=3)
        
    # 푸터
    draw.text((20, height - 25), "⚡ 쿠팡 파트너스 매일 가격 비교 실시간 동적 위젯", fill="#a6adc8", font=font_small)
    
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()

def generate_price_chart_bytes(product_id: str) -> bytes:
    """특정 상품 ID의 최신 DB 기록으로 차트 이미지 바이너리를 생성합니다."""
    # DB에서 상품 및 히스토리 조회
    all_prods = collector.get_all_products_from_db()
    product_info = next((p for p in all_prods if p["product_id"] == product_id), None)
    
    # [삭제됨] 상품이 없으면 "쿠팡 핫딜 추천 상품 50,000원"이라는 가짜 상품을,
    # 이력이 없으면 60000→58000→55000→50000 이라는 가짜 4점을 만들어 차트를 그렸다.
    # 그 그림이 블로그 본문에 "실제 판매가 추이"라는 설명과 함께 실렸다.
    # 이제는 근거가 없으면 그리지 않는다. 호출자는 None 을 받고 그래프를 생략해야 한다.
    if not product_info:
        raise ValueError(f"DB 에 상품 {product_id} 이(가) 없습니다 — 차트를 만들지 않습니다")

    # 실측이 아닌 상품(수집 실패 시 만들어지는 샘플 100건)은 차트를 그리지 않는다.
    # 이걸 막지 않으면, 샘플 상품도 하루 1점씩 쌓여 사흘 뒤엔 3점 문턱을 넘고
    # "확인한 시점들의 판매가 기록"이라는 설명이 붙은 그래프가 만들어진다.
    if int(product_info.get("is_real") or 0) != 1:
        raise ValueError(f"상품 {product_id} 은 실측 데이터가 아닙니다 — 차트를 만들지 않습니다")

    history_data = collector.get_price_history(product_id, days=14)
    if len(history_data or []) < MIN_POINTS_FOR_CHART:
        raise ValueError(
            f"관측 {len(history_data or [])}점 — 추이를 그리려면 최소 {MIN_POINTS_FOR_CHART}점이 필요합니다"
        )


    if HAS_MATPLOTLIB:
        try:
            return render_chart_with_matplotlib(product_info, history_data)
        except Exception as e:
            print(f"[Chart Error] Matplotlib fallback to Pillow: {e}")
            
    return render_chart_fallback_pillow(product_info, history_data)

def save_widget_chart_image(product_id: str, output_path: str = None) -> str:
    """차트 이미지를 파일로 저장합니다."""
    if not output_path:
        output_path = os.path.join(OUTPUT_DIR, f"price_chart_{product_id}.png")
        
    img_bytes = generate_price_chart_bytes(product_id)
    with open(output_path, "wb") as f:
        f.write(img_bytes)
        
    return output_path

# ── Flask 동적 위젯 웹 서버 ──
if HAS_FLASK:
    app = Flask(__name__)
    
    @app.route("/widget/chart/<product_id>.png")
    def serve_chart_png(product_id):
        """차트 PNG 제공. 관측이 부족하면 500 대신 404 — 없는 그림이지 서버 오류가 아니다."""
        try:
            img_bytes = generate_price_chart_bytes(product_id)
        except ValueError as e:
            return str(e), 404
        response = send_file(io.BytesIO(img_bytes), mimetype='image/png')
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        return response

    @app.route("/widget/view/<product_id>")
    def serve_widget_page(product_id):
        """모바일/웹 반응형 위젯 카드 페이지"""
        all_prods = collector.get_all_products_from_db()
        prod = next((p for p in all_prods if p["product_id"] == product_id), None)
        if not prod:
            return "상품 정보를 찾을 수 없습니다.", 404
            
        comp = prod.get("comparison", {})
        # 그릴 수 없으면 <img> 자체를 빼서 깨진 이미지 아이콘이 뜨지 않게 한다.
        has_chart = len(collector.get_price_history(product_id, days=14) or []) >= MIN_POINTS_FOR_CHART
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>{{ prod.title }} - 실시간 가격 그래프</title>
            <style>
                body { background:#121218; color:#e0e0e0; font-family:'Malgun Gothic', sans-serif; margin:0; padding:15px; display:flex; justify-content:center; }
                .card { background:#1e1e2e; max-width:480px; width:100%; border-radius:16px; padding:20px; box-shadow:0 8px 24px rgba(0,0,0,0.5); border:1px solid #313150; }
                .badge { background:#f38ba8; color:#fff; font-weight:bold; padding:4px 10px; border-radius:12px; font-size:12px; display:inline-block; }
                .title { font-size:16px; font-weight:bold; margin:10px 0; line-height:1.4; color:#cdd6f4; }
                .price-row { display:flex; align-items:baseline; gap:10px; margin:15px 0; }
                .curr-price { font-size:24px; font-weight:bold; color:#a6e3a1; }
                .orig-price { text-decoration:line-through; color:#a6adc8; font-size:14px; }
                .disc { color:#f9e2af; font-weight:bold; font-size:18px; }
                .comp-box { background:#252538; padding:12px; border-radius:10px; margin:12px 0; font-size:13px; border-left:4px solid #89b4fa; }
                .chart-img { width:100%; border-radius:10px; margin-top:10px; }
                .btn { display:block; text-align:center; background:#89b4fa; color:#11111b; font-weight:bold; padding:14px; border-radius:12px; text-decoration:none; margin-top:20px; font-size:16px; }
            </style>
        </head>
        <body>
            <div class="card">
                <span class="badge">🔥 쿠팡 파트너스 가격 추적</span>
                <div class="title">{{ prod.title }}</div>
                <div class="price-row">
                    <span class="curr-price">{{ "{:,}".format(prod.current_price) }}원</span>
                    <span class="orig-price">{{ "{:,}".format(prod.original_price) }}원</span>
                    <span class="disc">{{ prod.discount_rate }}% OFF</span>
                </div>
                <div class="comp-box">
                    {% if comp.has_prior %}
                    직전 확인 가격: <b>{{ "{:,}".format(comp.yesterday_price) }}원</b> <br>
                    {% if comp.status == 'down' %}
                    📉 <b>직전 대비 {{ "{:,}".format(comp.diff|abs) }}원 하락</b>
                    {% elif comp.status == 'up' %}
                    📈 직전 대비 {{ "{:,}".format(comp.diff|abs) }}원 상승
                    {% else %}
                    ➡️ 직전과 같은 가격
                    {% endif %}
                    {% else %}
                    ℹ️ 이전 확인 기록이 없어 비교할 수 없습니다.
                    {% endif %}
                </div>
                {% if has_chart %}
                <img class="chart-img" src="/widget/chart/{{ prod.product_id }}.png" alt="가격 기록 차트">
                {% endif %}
                <a class="btn" href="{{ prod.affiliate_url }}" target="_blank">🛒 쿠팡에서 현재 가격 확인하기</a>
            </div>
        </body>
        </html>
        """
        return render_template_string(html, prod=prod, comp=comp, has_chart=has_chart)

def start_widget_server(host="0.0.0.0", port=5050):
    """Flask 위젯 서버를 비동기로 시작합니다."""
    if not HAS_FLASK:
        print("[Widget Server] Flask library missing.")
        return
    import threading
    t = threading.Thread(target=lambda: app.run(host=host, port=port, debug=False, use_reloader=False), daemon=True)
    t.start()
    print(f"[Widget Server] Dynamic Widget Server active at http://localhost:{port}")

if __name__ == "__main__":
    print("[Price Widget Server] Testing chart generation...")
    chart_path = save_widget_chart_image("CP100_001")
    print(f"[Price Widget Server] Chart image saved successfully at: {chart_path}")
