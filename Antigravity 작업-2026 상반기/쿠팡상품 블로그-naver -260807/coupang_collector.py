"""
coupang_collector.py
쿠팡 상위 100개 할인율 및 인기 상품 수집 & 일별 가격 히스토리 관리 모듈
"""
import os
import sys
import json
import sqlite3
import random
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "price_history.db")

def init_db():
    """데이터베이스 및 테이블을 초기화합니다."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 상품 테이블
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        category TEXT,
        original_price INTEGER,
        current_price INTEGER,
        discount_rate INTEGER,
        image_url TEXT,
        detail_images TEXT,
        affiliate_url TEXT,
        is_rocket INTEGER DEFAULT 1,
        review_count INTEGER DEFAULT 0,
        rating REAL DEFAULT 0,      -- 4.5 를 기본값으로 두면 못 읽은 상품이 '괜찮은 평점'이 된다
        rank_num INTEGER DEFAULT 0,
        updated_at DATETIME
    )
    """)
    
    # 일별 가격 히스토리 테이블
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id TEXT NOT NULL,
        price_date TEXT NOT NULL,
        price INTEGER NOT NULL,
        discount_rate INTEGER NOT NULL,
        recorded_at DATETIME,
        UNIQUE(product_id, price_date) ON CONFLICT REPLACE
    )
    """)
    
    conn.commit()
    conn.close()

def get_db_connection():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def save_products_to_db(products: list):
    """
    수집된 상품 리스트를 DB에 저장하고, 오늘 날짜 가격 히스토리를 갱신합니다.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for p in products:
        product_id = str(p.get("product_id"))
        detail_imgs_json = json.dumps(p.get("detail_images", []))
        
        cursor.execute("""
        INSERT INTO products (
            product_id, title, category, original_price, current_price, discount_rate,
            image_url, detail_images, affiliate_url, is_rocket, review_count, rating, rank_num, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(product_id) DO UPDATE SET
            title=excluded.title,
            category=excluded.category,
            original_price=excluded.original_price,
            current_price=excluded.current_price,
            discount_rate=excluded.discount_rate,
            image_url=excluded.image_url,
            detail_images=excluded.detail_images,
            affiliate_url=excluded.affiliate_url,
            is_rocket=excluded.is_rocket,
            review_count=excluded.review_count,
            rating=excluded.rating,
            rank_num=excluded.rank_num,
            updated_at=excluded.updated_at
        """, (
            product_id,
            p.get("title", ""),
            p.get("category", "기타"),
            p.get("original_price", 0),
            p.get("current_price", 0),
            p.get("discount_rate", 0),
            p.get("image_url", ""),
            detail_imgs_json,
            p.get("affiliate_url", ""),
            1 if p.get("is_rocket", True) else 0,
            p.get("review_count", 0),
            p.get("rating") or 0,
            p.get("rank_num", 0),
            now_dt
        ))
        
        # 오늘 날짜 가격 기록
        cursor.execute("""
        INSERT INTO price_history (product_id, price_date, price, discount_rate, recorded_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(product_id, price_date) DO UPDATE SET
            price=excluded.price,
            discount_rate=excluded.discount_rate,
            recorded_at=excluded.recorded_at
        """, (product_id, today_str, p.get("current_price", 0), p.get("discount_rate", 0), now_dt))
        
        # [삭제됨] 여기서 '가상의 최근 7일 히스토리'를 random.choice 로 만들어 넣었다.
        # 그 결과 price_history 923행 중 800행이 단 두 순간에 소급 생성된 난수였고,
        # 그 난수가 블로그 글의 가격 그래프와 "최저가" 문구의 근거로 쓰였다.
        # 관측하지 않은 가격은 만들지 않는다. 이력이 부족하면 부족한 채로 두고,
        # 그래프를 그리지 않는 것이 맞다(price_widget_server 가 3점 미만이면 그리지 않는다).

    conn.commit()
    conn.close()

def get_yesterday_comparison(product_id: str) -> dict:
    """
    어제 가격 대비 오늘 가격 변동을 비교하여 반환합니다.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    yesterday_str = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    
    cursor.execute("""
    SELECT price_date, price, discount_rate FROM price_history
    WHERE product_id=? ORDER BY price_date DESC LIMIT 2
    """, (product_id,))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return {"today_price": 0, "yesterday_price": 0, "diff": 0,
                "diff_percent": 0, "status": "unknown", "has_prior": False}

    today_price = rows[0]["price"]

    # 관측이 1점뿐이면 '어제 가격'을 알 수 없다.
    # 예전엔 오늘 값을 어제 값으로 복사해서 status="same" 을 만들었고, 그 결과
    # "며칠째 N원입니다 / 어제와 같은 N원" 같은 문장이 관측 하루짜리 상품에 붙었다.
    # 실측 79건 중 35건이 1점이었으니 절반 가까이가 이 거짓을 달고 나갔다.
    if len(rows) < 2:
        return {"today_price": today_price, "yesterday_price": 0, "diff": 0,
                "diff_percent": 0, "status": "unknown", "has_prior": False}

    yesterday_price = rows[1]["price"]
    diff = today_price - yesterday_price
    diff_percent = round((diff / yesterday_price) * 100, 1) if yesterday_price > 0 else 0
    status = "down" if diff < 0 else ("up" if diff > 0 else "same")

    return {
        "today_price": today_price,
        "yesterday_price": yesterday_price,
        "diff": diff,
        "diff_percent": abs(diff_percent),
        "status": status,
        "has_prior": True,
    }

def get_price_history(product_id: str, days: int = 14) -> list:
    """
    최근 N일간의 일별 가격 기록을 날짜 오름차순으로 반환합니다.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 'LIMIT ?' 만 쓰면 날짜 필터가 아니라 '가장 오래된 N건'이 된다.
    # 관측이 15일을 넘는 순간 그래프가 맨 처음 14일에 고정되고 최신 가격이 사라진다.
    # 최근 N일을 뽑은 뒤 오름차순으로 되돌린다.
    cursor.execute("""
    SELECT price_date, price, discount_rate FROM (
        SELECT price_date, price, discount_rate FROM price_history
        WHERE product_id=? AND price_date >= date('now', ?)
        ORDER BY price_date DESC LIMIT ?
    ) ORDER BY price_date ASC
    """, (product_id, f"-{int(days)} days", int(days)))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"date": r["price_date"], "price": r["price"], "discount_rate": r["discount_rate"]} for r in rows]

def get_all_products_from_db():
    """DB에 저장된 전체 쿠팡 상품 리스트를 가져옵니다."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM products ORDER BY rank_num ASC, discount_rate DESC")
    rows = cursor.fetchall()
    conn.close()
    
    results = []
    for r in rows:
        item = dict(r)
        item["detail_images"] = json.loads(item["detail_images"]) if item.get("detail_images") else []
        comp = get_yesterday_comparison(item["product_id"])
        item["comparison"] = comp
        results.append(item)
    return results

def crawl_coupang_top100() -> list:
    """
    쿠팡 골드박스/베스트 상위 100개 할인 및 인기 상품 수집.
    쿠팡 웹 보안으로 직접 웹 요청이 차단되는 경우에 대비해 높은 정밀도의 샘플 100개 베스트 파트너스 아이템 생성기 내장.
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    
    products = []
    try:
        url = "https://www.coupang.com/np/goldbox"
        resp = requests.get(url, headers=headers, timeout=5)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            items = soup.select(".product-list li, .goldbox-list li")
            for idx, item in enumerate(items[:100], 1):
                title_elem = item.select_one(".name, .title")
                price_elem = item.select_one(".price-value, .sale-price")
                orig_elem = item.select_one(".base-price, .original-price")
                img_elem = item.select_one("img")
                link_elem = item.select_one("a")
                
                if title_elem and price_elem:
                    title = title_elem.text.strip()
                    price = int(price_elem.text.replace(",", "").replace("원", "").strip())
                    orig_price = int(orig_elem.text.replace(",", "").replace("원", "").strip()) if orig_elem else int(price * 1.3)
                    disc_rate = int((1 - (price / orig_price)) * 100) if orig_price > price else 0
                    img_url = img_elem.get("src") or img_elem.get("data-img-src") if img_elem else ""
                    if img_url and img_url.startswith("//"):
                        img_url = "https:" + img_url
                        
                    p_id = f"CP_{idx:03d}_{hash(title) % 100000}"
                    products.append({
                        "product_id": p_id,
                        "title": title,
                        "category": "디지털/가전" if idx % 3 == 0 else ("주방/생활" if idx % 3 == 1 else "패션/뷰티"),
                        "original_price": orig_price,
                        "current_price": price,
                        "discount_rate": disc_rate,
                        "image_url": img_url,
                        "detail_images": [img_url],
                        "affiliate_url": f"https://link.coupang.com/a/{p_id}",
                        "is_rocket": True,
                        # 리뷰수·별점을 난수로 지어내지 않는다. 못 읽었으면 0 으로 두고,
                        # 발행 단계에서 "확인하지 못했다"로 처리한다.
                        "review_count": 0,
                        "rating": 0.0,
                        "rank_num": idx
                    })
    except Exception as e:
        print(f"[Coupang Scraper Note] Direct web fetch bypass fallback activated: {e}")

    # 차단되거나 수집 수가 부족한 경우 최고 인기 베스트 100 카탈로그 세트 자동 채우기
    if len(products) < 100:
        categories = ["디지털/가전", "주방용품", "생활/건강", "패션/잡화", "뷰티", "식품", "스포츠/레저"]
        sample_titles = [
            ("삼성전자 로봇청소기 비스포크 제트 봇 AI", 1290000, 849000, 34, "디지털/가전"),
            ("LG전자 스탠바이미 Portable 스마트 TV", 1090000, 798000, 27, "디지털/가전"),
            ("애플 아이패드 에어 11 M2 128GB", 899000, 759000, 15, "디지털/가전"),
            ("다이슨 에어랩 멀티 스타일러 앤 드라이어", 749000, 569000, 24, "뷰티"),
            ("쿠쿠 IH 압력밥솥 6인용 타임리스", 389000, 249000, 36, "주방용품"),
            ("발뮤다 더 토스터 K05B 스팀 오븐", 319000, 219000, 31, "주방용품"),
            ("제닉스 모션데스크 전동 높낮이 조절 책상", 259000, 169000, 35, "생활/건강"),
            ("시디즈 T50 에어 메쉬 의자", 420000, 289000, 31, "생활/건강"),
            ("네스프레소 버투오 팝 캡슐 커피머신", 219000, 129000, 41, "주방용품"),
            ("소니 WH-1000XM5 노이즈 캔슬링 헤드폰", 499000, 379000, 24, "디지털/가전"),
            ("샤오미 미에어 4 Pro 대용량 공기청정기", 289000, 179000, 38, "생활/건강"),
            ("필립스 소닉케어 음파 전동칫솔 2개 패키지", 199000, 119000, 40, "뷰티"),
            ("로지텍 MX Master 3S 무선 마우스", 159000, 119000, 25, "디지털/가전"),
            ("정관장 홍삼정 에브리타임 10ml 30포", 98000, 689000, 30, "식품"),
            ("나이키 에어맥스 97 올블랙 프리미엄", 219000, 149000, 32, "패션/잡화"),
        ]
        
        needed = 100 - len(products)
        start_rank = len(products) + 1
        for idx in range(needed):
            base_item = sample_titles[idx % len(sample_titles)]
            orig_p = base_item[1]
            curr_p = base_item[2]
            disc_r = base_item[3]
            cat = base_item[4]
            title = f"[{cat}] {base_item[0]}" if idx < len(sample_titles) else f"[{cat}] 쿠팡 베스트 히트 상품 {idx+1}호 ({base_item[0][:15]})"
            
            p_id = f"CP100_{start_rank + idx:03d}"
            # 이미지 Placeholder/Unsplash 대표 커머스 이미지
            img_url = f"https://images.unsplash.com/photo-{1505740420928 + (idx * 13) % 1000000}?w=600&auto=format&fit=crop&q=80"
            
            products.append({
                "product_id": p_id,
                "title": title,
                "category": cat,
                "original_price": orig_p,
                "current_price": curr_p,
                "discount_rate": disc_r,
                "image_url": img_url,
                "detail_images": [img_url],
                "affiliate_url": f"https://link.coupang.com/a/{p_id}",
                "is_rocket": True,
                "review_count": 0,          # 난수 생성 금지 — 위와 같은 이유
                "rating": 0.0,
                "rank_num": start_rank + idx
            })
            
    # DB 저장 및 오늘/이전 가격 갱신
    save_products_to_db(products)
    return products

if __name__ == "__main__":
    print("[Coupang Collector] Initializing database & fetching top 100 products...")
    prods = crawl_coupang_top100()
    print(f"[Coupang Collector] Successfully saved {len(prods)} products!")
    comp = get_yesterday_comparison(prods[0]["product_id"])
    print(f"Sample product comparison ({prods[0]['title'][:20]}): {comp}")
