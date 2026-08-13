"""
coupang_live_collector.py
쿠팡 실측 수집기 — Playwright 실제 브라우저로 골드박스 목록과 상품 상세페이지를 수집한다.

기존 coupang_collector.py 와의 관계:
  - 기존 모듈은 requests + BeautifulSoup 단발 요청이라 Akamai 봇차단(403)에 항상 막히고,
    실패하면 하드코딩 샘플 15종을 100개로 복제하는 폴백이 동작해 가짜 데이터가 DB에 쌓였다.
  - 이 모듈은 그 폴백이 없다. 못 가져오면 예외를 던진다.
  - 기존 파일은 수정하지 않는다. DB 스키마만 ALTER TABLE 로 확장해 공유한다.

수집 경로 (2026-08 실측 기준):
  목록  https://www.coupang.com/np/campaigns/82   (골드박스, 스크롤 시 60건)  → 통과
  상세  https://www.coupang.com/vp/products/{id}                            → 조건부

Akamai 우회 — 실측으로 확정한 것 (2026-08-09):
  통과 조건 (목록):
    · headless 금지. 구형/신형(--headless=new) 모두 차단된다. 창을 띄워야 한다.
    · user_agent 오버라이드 금지. 위조 UA 와 sec-ch-ua 클라이언트 힌트가 어긋나면
      Akamai 가 모순을 잡아낸다. 봇을 피하려 넣은 위조가 곧 봇 신호였다.
    · extra_http_headers 로 Accept-Language 강제 금지 (헤더 순서가 달라진다).
    · locale="ko-KR" 필수. 이걸 빼면 차단된다.
    · 홈에서 사람처럼 움직이며 워밍업(_warmup) 후 목표 경로로 이동.

  상세페이지(/vp/products/)는 위 조건을 모두 만족해도 새로 띄운 세션에서는
  "요청하신 페이지의 사용권한이 없습니다" 로 막히는 경우가 있다. 아래는 전부 시도했고
  전부 실패했다 — 같은 함정을 다시 파지 않도록 기록해 둔다:
    · 영속 프로필 재사용, 실제 Chrome 채널(channel="chrome"), GPU 강제(실제 RTX 지문 일치)
    · 기존 브라우저 세션 쿠키 15종 주입, 목록에서 hover 후 클릭 진입, referer 지정
    · 홈 12초 + 목록 25초 체류 등 사람 동선 재현
    · 독립 실행 Chrome 에 connect_over_cdp 접속
  반면 오래 살아 있던 기존 브라우저 세션에서는 같은 시각·같은 IP 에서 정상 열렸다.
  → 세션 연령/평판 기반 제한으로 보인다. 목록 수집만으로도 릴스·블로그에 필요한
    제목·가격·할인률·평점·리뷰수·이미지·상세URL 은 모두 확보된다.

상세 수집 폴백 (2026-08-10 추가):
  위 실패 목록은 전부 '데스크톱 Playwright 세션을 더 사람처럼 보이게' 만드는 시도였다.
  같은 문 앞에서 노크만 25번 한 셈이다. 그래서 문 자체를 늘렸다 — backend_router 로
  경로 후보를 순서대로 시도하고, 첫 '완전 성공'을 채택한다:

    1) browser-desktop  www.coupang.com/vp/products/{id}   (기존 경로, 실측 검증됨)
    2) browser-mobile   m.coupang.com/vm/products/{id}     (미검증 — 아래 주의)
    3) jina-reader      r.jina.ai 프록시 렌더링             (미검증 — 외부 서비스)

  ※ 2·3 번은 아직 실측하지 않았다. 실패해도 1 번 동작에는 영향이 없도록
    (실패 = 다음 후보로 넘어감) 짜 두었으니, 한 번 돌려 보고 doctor 출력으로
    쓸모를 판단하면 된다. 안 되면 DETAIL_BACKENDS 에서 빼면 그만이다.

  판정은 '페이지가 열렸는가'가 아니라 '알맹이가 왔는가'로 한다(classify_detail).
  예전 코드는 제목만 있고 가격·이미지가 0 인 하이드레이션 미완 페이지를 OK 로
  출력했다 — DB 는 가드가 지켜 줬지만 로그가 거짓말을 했다.

  우선순위 강제:  COUPANG_DETAIL_BACKEND=jina-reader python ... enrich 3

사용법:
  python coupang_live_collector.py list            # 목록만 수집  ← 현재 안정 동작
  python coupang_live_collector.py full [개수]      # 목록 + 상세 (상세 실패 시 목록값 유지)
  python coupang_live_collector.py detail <URL|ID>  # 단일 상세페이지
  python coupang_live_collector.py enrich [개수]    # 상세 점진 보강 (간격 두고 소량씩)
  python coupang_live_collector.py doctor           # 백엔드·환경 점검 (수집 안 함)
"""
import os
import re
import sys
import json
import time
import sqlite3
import random
from datetime import datetime

from backend_router import Attempt, pick, run_chain, summarize

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "price_history.db")

GOLDBOX_URL = "https://www.coupang.com/np/campaigns/82"

# 이미지 다운로드(requests)용 UA. 브라우저 컨텍스트에는 절대 넣지 않는다 —
# UA 를 위조하면 sec-ch-ua 클라이언트 힌트와 어긋나 Akamai 가 차단한다.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


# ════════════════════════════════════════════════════════════════
# DB — 기존 스키마를 깨지 않고 컬럼만 덧붙인다
# ════════════════════════════════════════════════════════════════

NEW_COLUMNS = [
    ("detail_url", "TEXT"),        # 상세페이지 주소 — 릴스 생성의 입력이 된다
    ("vendor_item_id", "TEXT"),
    ("item_id", "TEXT"),
    ("brand", "TEXT"),
    ("monthly_buyers", "TEXT"),    # "한 달간 9,000명 이상 구매했어요"
    ("delivery_info", "TEXT"),     # "내일(월) 8/10 도착 보장"
    ("specs", "TEXT"),             # JSON — 제조년월일/재질/구성 등
    ("thumbnails", "TEXT"),        # JSON — 갤러리 이미지(고해상도 치환본)
    ("is_real", "INTEGER DEFAULT 0"),   # 1 = 실제 수집, 0 = 기존 더미
    ("collected_at", "DATETIME"),
]


def migrate_db():
    """기존 products 테이블에 실측용 컬럼을 추가한다. 이미 있으면 건너뛴다."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS products (
        product_id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT,
        original_price INTEGER, current_price INTEGER, discount_rate INTEGER,
        image_url TEXT, detail_images TEXT, affiliate_url TEXT,
        is_rocket INTEGER DEFAULT 1, review_count INTEGER DEFAULT 0,
        rating REAL DEFAULT 0, rank_num INTEGER DEFAULT 0, updated_at DATETIME
    )""")
    cur.execute("""
    CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, product_id TEXT NOT NULL,
        price_date TEXT NOT NULL, price INTEGER NOT NULL, discount_rate INTEGER NOT NULL,
        recorded_at DATETIME, UNIQUE(product_id, price_date) ON CONFLICT REPLACE
    )""")
    existing = {r[1] for r in cur.execute("PRAGMA table_info(products)")}
    added = []
    for name, decl in NEW_COLUMNS:
        if name not in existing:
            cur.execute(f"ALTER TABLE products ADD COLUMN {name} {decl}")
            added.append(name)
    conn.commit()
    conn.close()
    return added


def save_real_products(products: list) -> int:
    """
    실측 상품을 저장한다. 기존 save_products_to_db 와 달리
    '가상 7일치 히스토리 생성'을 하지 않는다 — 실제로 관측한 날짜만 기록한다.
    """
    if not products:
        return 0
    migrate_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for p in products:
        # 이미지 목록은 '비었는지'가 아니라 '더 풍부한지'로 판단해야 한다.
        # 목록 수집은 대표 이미지 1장만 주는데, 그게 상세 수집으로 모은 16장을
        # 덮어써 버린 적이 있다. 더 많이 가진 쪽을 남긴다.
        row = cur.execute(
            "SELECT detail_images, thumbnails, detail_url FROM products WHERE product_id=?",
            (p["product_id"],)).fetchone()
        if row:
            # 옵션 파라미터(itemId)가 붙은 URL 이 더 정확하다. 파라미터 없는 URL 로
            # 덮어쓰면 다음 상세 수집이 엉뚱한 옵션 페이지를 읽는다.
            old_url = row[2] or ""
            new_url = p.get("detail_url") or ""
            if "itemId=" in old_url and "itemId=" not in new_url:
                p["detail_url"] = old_url
            for key, idx in (("detail_images", 0), ("thumbnails", 1)):
                try:
                    old = json.loads(row[idx] or "[]")
                except Exception:
                    old = []
                new = p.get(key) or []
                if len(old) > len(new):
                    p[key] = old

        cur.execute("""
        INSERT INTO products (
            product_id, title, category, original_price, current_price, discount_rate,
            image_url, detail_images, affiliate_url, is_rocket, review_count, rating,
            rank_num, updated_at, detail_url, vendor_item_id, item_id, brand,
            monthly_buyers, delivery_info, specs, thumbnails, is_real, collected_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?)
        ON CONFLICT(product_id) DO UPDATE SET
            -- 빈 값으로 기존 값을 덮어쓰지 않는다.
            -- 상세 수집만 단독 실행하면 목록에서 얻은 가격·리뷰수가 0 으로 밀려
            -- DB 가 망가진다(실제로 겪음: 167,700원 → 0, 리뷰 75,742 → 0).
            title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE products.title END,
            category=CASE WHEN excluded.category<>'' THEN excluded.category ELSE products.category END,
            original_price=CASE WHEN excluded.original_price>0 THEN excluded.original_price ELSE products.original_price END,
            current_price=CASE WHEN excluded.current_price>0 THEN excluded.current_price ELSE products.current_price END,
            discount_rate=CASE WHEN excluded.discount_rate>0 THEN excluded.discount_rate ELSE products.discount_rate END,
            image_url=CASE WHEN excluded.image_url<>'' THEN excluded.image_url ELSE products.image_url END,
            detail_images=CASE WHEN excluded.detail_images NOT IN ('','[]') THEN excluded.detail_images ELSE products.detail_images END,
            affiliate_url=CASE WHEN excluded.affiliate_url<>'' THEN excluded.affiliate_url ELSE products.affiliate_url END,
            is_rocket=excluded.is_rocket,
            review_count=CASE WHEN excluded.review_count>0 THEN excluded.review_count ELSE products.review_count END,
            rating=CASE WHEN excluded.rating>0 AND excluded.rating<=5 THEN excluded.rating ELSE products.rating END,
            rank_num=CASE WHEN excluded.rank_num>0 THEN excluded.rank_num ELSE products.rank_num END,
            updated_at=excluded.updated_at,
            detail_url=CASE WHEN excluded.detail_url<>'' THEN excluded.detail_url ELSE products.detail_url END,
            vendor_item_id=CASE WHEN excluded.vendor_item_id<>'' THEN excluded.vendor_item_id ELSE products.vendor_item_id END,
            item_id=CASE WHEN excluded.item_id<>'' THEN excluded.item_id ELSE products.item_id END,
            brand=CASE WHEN excluded.brand<>'' THEN excluded.brand ELSE products.brand END,
            monthly_buyers=CASE WHEN excluded.monthly_buyers<>'' THEN excluded.monthly_buyers ELSE products.monthly_buyers END,
            delivery_info=CASE WHEN excluded.delivery_info<>'' THEN excluded.delivery_info ELSE products.delivery_info END,
            specs=CASE WHEN excluded.specs NOT IN ('','{}') THEN excluded.specs ELSE products.specs END,
            thumbnails=CASE WHEN excluded.thumbnails NOT IN ('','[]') THEN excluded.thumbnails ELSE products.thumbnails END,
            is_real=1, collected_at=excluded.collected_at
        """, (
            p["product_id"], p["title"], p.get("category", ""),
            p.get("original_price", 0), p.get("current_price", 0), p.get("discount_rate", 0),
            p.get("image_url", ""), json.dumps(p.get("detail_images", []), ensure_ascii=False),
            p.get("affiliate_url", ""), 1 if p.get("is_rocket") else 0,
            p.get("review_count", 0), p.get("rating", 0.0), p.get("rank_num", 0), now,
            p.get("detail_url", ""), p.get("vendor_item_id", ""), p.get("item_id", ""),
            p.get("brand", ""), p.get("monthly_buyers", ""), p.get("delivery_info", ""),
            json.dumps(p.get("specs", {}), ensure_ascii=False),
            json.dumps(p.get("thumbnails", []), ensure_ascii=False), now,
        ))
        if p.get("current_price"):
            cur.execute("""
            INSERT INTO price_history (product_id, price_date, price, discount_rate, recorded_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(product_id, price_date) DO UPDATE SET
                price=excluded.price, discount_rate=excluded.discount_rate,
                recorded_at=excluded.recorded_at
            """, (p["product_id"], today, p["current_price"], p.get("discount_rate", 0), now))

    conn.commit()
    conn.close()
    return len(products)


# ════════════════════════════════════════════════════════════════
# 브라우저
# ════════════════════════════════════════════════════════════════

def _new_context(pw, headless=False):
    """
    쿠팡 Akamai 를 통과하는 유일한 조합. 실측으로 확정했다(2026-08).

    절대 하지 말 것:
      · user_agent 오버라이드 — 위조한 UA 문자열과 브라우저가 실제 보내는
        sec-ch-ua 클라이언트 힌트가 어긋나면 Akamai 가 모순을 잡아내 /np/* 를 403 한다.
        봇을 피하려고 넣은 UA 위조가 오히려 봇 신호가 된다.
      · extra_http_headers 로 Accept-Language 강제 — 헤더 순서가 네이티브와 달라진다.

    반드시 할 것:
      · locale="ko-KR"  (이걸 빼면 차단된다. 실측에서 '완전 기본값'은 실패했다)
      · --disable-blink-features=AutomationControlled
      · _warmup() 으로 홈에서 _abck 쿠키 검증을 통과시킨 뒤 목표 경로로 이동
    """
    browser = pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )
    ctx = browser.new_context(
        locale="ko-KR", timezone_id="Asia/Seoul",
        viewport={"width": 1440, "height": 960},
    )
    return browser, ctx


def _abck_valid(ctx) -> bool:
    """Akamai _abck 쿠키가 검증을 통과했는지. ~0~ 이면 통과, ~-1~ 이면 미검증."""
    for c in ctx.cookies():
        if c["name"] == "_abck":
            m = re.search(r"~(-?\d)~", c["value"])
            return bool(m and m.group(1) == "0")
    return False


def _warmup(page, ctx, max_wait=14.0) -> bool:
    """
    홈에서 사람처럼 움직여 Akamai 센서가 _abck 를 검증하게 만든다.
    실측상 8초 안팎에서 ~-1~ → ~0~ 으로 바뀐다. 이 단계를 건너뛰면 보호 경로가 막힌다.
    """
    page.goto("https://www.coupang.com/", wait_until="domcontentloaded", timeout=45000)
    waited, i = 0.0, 0
    while waited < max_wait:
        page.mouse.move(300 + (i % 8) * 55, 260 + (i % 4) * 80)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(900)
        waited += 0.9
        i += 1
        if _abck_valid(ctx):
            print(f"[워밍업] Akamai 검증 통과 ({waited:.1f}s)")
            return True
    print(f"[워밍업] 검증 미확인 — 그대로 진행 ({waited:.1f}s)")
    return False


def hi_res(url: str, size: int = 1000) -> str:
    """쿠팡 CDN 썸네일 URL의 해상도 세그먼트를 키운다. 230x230ex → 1000x1000ex"""
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    return re.sub(r"/remote/\d+x\d+ex/", f"/remote/{size}x{size}ex/", url)


# ════════════════════════════════════════════════════════════════
# 1) 골드박스 목록
# ════════════════════════════════════════════════════════════════

_LIST_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  let last = 0;
  for (let i = 0; i < 12; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await sleep(700);
    const n = document.querySelectorAll('li[class*="ProductUnit_productUnit"]').length;
    if (n === last && i > 3) break;
    last = n;
  }
  window.scrollTo(0, 0);
  await sleep(300);

  const num = s => { const m = String(s||'').replace(/,/g,'').match(/\d+/); return m ? +m[0] : 0; };
  const pick = (root, sel) => { const e = root.querySelector(sel); return e ? e.innerText.trim() : ''; };

  return [...document.querySelectorAll('li[class*="ProductUnit_productUnit"]')].map((li, idx) => {
    const a = li.querySelector('a[href*="/vp/products/"]');
    if (!a) return null;
    const href = a.getAttribute('href') || '';
    const id  = (href.match(/\/vp\/products\/(\d+)/) || [])[1];
    if (!id) return null;
    const img = li.querySelector('img');
    return {
      product_id: id,
      title: pick(li, '[class*="productNameV2"]') || pick(li, '[class*="productName"]') || (img?.alt || ''),
      discount_rate: num(pick(li, '[class*="discountRate"]')),
      original_price: num(pick(li, '[class*="basePrice"]')),
      current_price: num(pick(li, '[class*="priceValue"]')),
      rating: parseFloat(pick(li, '[class*="ProductRating_star"]')) || 0,
      review_count: num(pick(li, '[class*="ratingCount"]')),
      image_url: img ? (img.src || img.dataset.src || '') : '',
      is_rocket: !!li.querySelector('[data-badge-id*="ROCKET"], img[alt*="로켓"]'),
      item_id: (href.match(/itemId=(\d+)/) || [])[1] || '',
      vendor_item_id: (href.match(/vendorItemId=(\d+)/) || [])[1] || '',
      detail_url: 'https://www.coupang.com' + href.split('?')[0] + '?itemId=' +
                  ((href.match(/itemId=(\d+)/) || [])[1] || '') + '&vendorItemId=' +
                  ((href.match(/vendorItemId=(\d+)/) || [])[1] || ''),
      rank_num: idx + 1,
    };
  }).filter(Boolean);
}
"""


def collect_goldbox(limit: int = 60, headless: bool = False) -> list:
    """골드박스 목록을 실제 브라우저로 수집한다. 한 건도 못 가져오면 예외."""
    from playwright.sync_api import sync_playwright

    print(f"[목록] {GOLDBOX_URL} 접속 중...")
    with sync_playwright() as pw:
        browser, ctx = _new_context(pw, headless)
        try:
            page = ctx.new_page()
            _warmup(page, ctx)
            page.goto(GOLDBOX_URL, wait_until="domcontentloaded", timeout=45000)
            try:
                page.wait_for_selector('li[class*="ProductUnit_productUnit"]', timeout=20000)
            except Exception:
                raise RuntimeError(
                    f"골드박스 상품 카드를 찾지 못했습니다 (title={page.title()!r}). "
                    "쿠팡이 차단했거나 페이지 구조가 바뀌었습니다."
                )
            items = page.evaluate(_LIST_JS)
        finally:
            ctx.close()
            browser.close()

    if not items:
        raise RuntimeError("수집 결과가 0건입니다.")

    for it in items:
        it["image_url"] = hi_res(it.get("image_url", ""))
        it["detail_images"] = [it["image_url"]] if it["image_url"] else []
        it["affiliate_url"] = it["detail_url"]   # 파트너스 미승인 — 원본 링크를 그대로 둔다
        it["category"] = ""
        # 할인률이 비었으면 정가/판매가로 직접 계산
        if not it.get("discount_rate") and it.get("original_price", 0) > it.get("current_price", 0) > 0:
            it["discount_rate"] = round((1 - it["current_price"] / it["original_price"]) * 100)

    items = [i for i in items if i.get("title") and i.get("current_price")][:limit]
    print(f"[목록] {len(items)}건 수집 완료")
    return items


# ════════════════════════════════════════════════════════════════
# 2) 상품 상세페이지  ← 릴스 소재의 핵심
# ════════════════════════════════════════════════════════════════

_DETAIL_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // 상세 설명 이미지는 lazy-load — 아래까지 훑어야 src 가 채워진다
  for (let y = 0; y < 6; y++) { window.scrollTo(0, document.body.scrollHeight * y / 6); await sleep(450); }
  window.scrollTo(0, 0);
  await sleep(400);

  const T = document.body.innerText;
  const one = re => { const m = T.match(re); return m ? m[1].trim() : ''; };
  const num = s => { const m = String(s||'').replace(/,/g,'').match(/\d+/); return m ? +m[0] : 0; };
  const q = s => document.querySelector(s);

  // 브레드크럼 = 진짜 카테고리
  const crumbs = [...document.querySelectorAll('#breadcrumb a, .breadcrumb a, [class*="breadcrumb"] a')]
    .map(a => a.innerText.trim()).filter(t => t && t !== '쿠팡 홈');

  // 상세 설명 이미지 (원본 고해상도)
  // 호스트 뒤 숫자를 반드시 허용해야 한다 — 쿠팡 CDN 은 thumbnail6/image7 처럼
  // 번호가 붙은 호스트로 분산 서빙한다. `thumbnail\.` 로만 쓰면 한 장도 안 걸린다.
  // image/displayitem/ 은 상품 사진이 아니라 쿠팡 공통 광고 배너다.
  // ("쿠팡에서 판매시작하기", "쿠팡 only" — 서로 무관한 6개 상품에서 동일한 5장이
  //  나온 것을 실물로 확인했다.) 판매자가 올린 vendor_inventory 만 상품 사진이다.
  const detailImgs = [...document.querySelectorAll('img')]
    .map(i => i.src || i.dataset.src || i.getAttribute('data-original') || '')
    .filter(u => /image\d*\.coupangcdn\.com\/image\/vendor_inventory/.test(u));

  // 상단 갤러리 썸네일 — 반드시 '상품 이미지 컨테이너 안에서만' 긁는다.
  // 예전엔 document 전체(img 541장)에서 긁어 '함께 본 상품' 캐러셀이 섞였고,
  // 아카페라 아메리카노 릴스에 전혀 다른 제품(아이브루) 사진이 두 씬 들어갔다.
  // 실측 구조:  div[class*="product-image"](3장) ⊂ .prod-atf(25장) ⊂ main(541장)
  const gal = document.querySelector('[class*="product-image"]')
           || document.querySelector('.prod-atf');
  const thumbs = (gal ? [...gal.querySelectorAll('img')] : [])
    .map(i => i.src || i.dataset.src || '')
    .filter(u => /thumbnail\d*\.coupangcdn\.com\/thumbnails\/remote\/\d+x\d+ex\//.test(u))
    .filter(u => !/logo|icon|badge|sprite/i.test(u));

  // 스펙 — "키: 값" 형태로 나열되는 구간
  const specs = {};
  T.split('\n').forEach(line => {
    const m = line.match(/^([가-힣A-Za-z/·\s]{2,20}):\s*(.{1,60})$/);
    if (m && !/^https?/.test(m[2])) specs[m[1].trim()] = m[2].trim();
  });

  // 가격 — 상품마다 '와우할인가/일반판매가' 문구가 있기도 없기도 하다.
  // 문구에 기대지 않고 "할인률% → 현재가 → 정가" 순서 패턴으로 잡는다.
  // 예: "88%\n18,670원\n(100ml당 156원)\n167,700원"  (실측 검증됨)
  const pm = T.match(/(\d{1,2})%\s*\n\s*([\d,]{3,})원[\s\S]{0,40}?([\d,]{4,})원/);
  const disc = pm ? +pm[1] : 0;
  let cur = pm ? num(pm[2]) : 0;
  let org = pm ? num(pm[3]) : 0;
  if (org && cur && org < cur) { const t2 = org; org = cur; cur = t2; }   // 뒤집힘 방어

  // 브랜드 — 브레드크럼 마지막은 카테고리 말단('커피음료')이지 브랜드가 아니다.
  // 실제 브랜드는 '브랜드샵' 링크 바로 앞줄에 온다('빙그레').
  const lines = T.split('\n').map(s => s.trim());
  const bi = lines.indexOf('브랜드샵');
  const brand = bi > 0 ? lines[bi - 1] : '';

  // 평점 — 본문에 숫자로 없고 별 너비(%)로만 표현된다. 100% = 5.0
  const rw = q('[class*="rating-star-num"]')?.getAttribute('style') || '';
  const rwm = rw.match(/width:\s*([\d.]+)%/);
  const rating = rwm ? Math.round((parseFloat(rwm[1]) / 20) * 10) / 10 : 0;

  return {
    title: (q('h1')?.innerText || q('.prod-buy-header__title')?.innerText || document.title.split(' - ')[0]).trim(),
    brand,
    category: crumbs.slice(0, 4).join(' > '),
    review_count: num(one(/([\d,]+)\s*개\s*상품평/)),
    rating,
    monthly_buyers: one(/(한 달간 [^\n]{2,40}구매했어요)/),
    delivery_info: one(/(내일[^\n]{0,40}도착[^\n]{0,20}|모레[^\n]{0,40}도착[^\n]{0,20}|무료배송[^\n]{0,24})/),
    discount_rate: disc,
    original_price: org,
    current_price: cur,
    detail_images: [...new Set(detailImgs)].slice(0, 20),
    thumbnails: [...new Set(thumbs)].slice(0, 12),
    specs,
  };
}
"""


#: 상세 접근 경로 후보 — 앞에 있을수록 우선. 순서만 바꾸면 우선순위가 바뀐다.
#  COUPANG_DETAIL_BACKEND 로 특정 백엔드를 맨 앞으로 끌어올릴 수 있다.
DETAIL_BACKENDS = ["browser-desktop", "browser-mobile", "jina-reader"]

DETAIL_BACKEND_ENV = "COUPANG_DETAIL_BACKEND"

#: 차단됐을 때 쿠팡이 돌려주는 제목. 본문은 249자짜리 "사용권한이 없습니다" 안내다.
_BLOCKED_TITLES = ("", "쿠팡!", "Access Denied")


def parse_product_url(url_or_id: str):
    """
    '12345' / 전체 URL 어느 쪽이든 (product_id, 정규화된 데스크톱 URL) 로 바꾼다.

    ID 만 받았을 때는 DB 에 저장된 detail_url(itemId·vendorItemId 포함)을 우선 쓴다.
    이 파라미터가 없으면 쿠팡이 '기본 옵션' 페이지를 보여주는데, 그게 목록에서
    수집한 옵션과 다르다. 실제로 12개입(18,670원) 상품을 ID 로만 조회했다가
    24개입(36,160원) 페이지를 받아 DB 의 제목·가격·이력이 통째로 뒤바뀐 적이 있다.
    """
    s = str(url_or_id).strip()
    if s.isdigit():
        try:
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                "SELECT detail_url FROM products WHERE product_id=?", (s,)).fetchone()
            conn.close()
            if row and row[0] and "itemId=" in row[0]:
                return s, row[0]
        except Exception:
            pass
        return s, f"https://www.coupang.com/vp/products/{s}"
    url = s if s.startswith("http") else "https://" + s
    m = re.search(r"/v[pm]/products/(\d+)", url)
    if not m:
        raise ValueError(f"쿠팡 상품 URL이 아닙니다: {url}")
    return m.group(1), url


def classify_detail(d: dict) -> str:
    """
    받아온 상세 데이터가 릴스 소재로 쓸 만한지 판정한다.

    '페이지가 열렸다'와 '데이터가 왔다'는 다른 얘기다. 하이드레이션이 덜 끝나면
    제목만 나오고 가격·이미지가 통째로 0 인 채로 반환되는데, 예전 코드는 이걸
    성공으로 세고 "OK" 를 찍었다. 여기서 partial 로 떨어뜨려야 뒤에 있는 다른
    백엔드가 시도될 기회를 얻는다.
    """
    if not d or not (d.get("title") or "").strip():
        return "blocked"
    n_img = len(d.get("detail_images") or []) + len(d.get("thumbnails") or [])
    has_price = (d.get("current_price") or 0) > 0
    return "ok" if (has_price and n_img >= 1) else "partial"


def _detail_note(d: dict) -> str:
    return (f"이미지 {len(d.get('detail_images') or []) + len(d.get('thumbnails') or [])}장, "
            f"가격 {d.get('current_price') or 0:,}원, 리뷰 {d.get('review_count') or 0:,}개")


# ── 백엔드 1·2: 실제 브라우저 ────────────────────────────────────

def _bk_browser(page, url: str, wait_ms: int = 3200):
    """
    이미 워밍업된 page 로 URL 을 연다. page 가 없으면 None — 이 백엔드는 후보에서 빠진다
    (브라우저 없이 jina 만으로 돌리는 경우가 있다).
    """
    if page is None:
        return None
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    # 하이드레이션이 덜 끝난 상태에서 읽으면 상품평·가격이 통째로 비어 0 이 된다.
    # 1.8초로는 부족했다(실측). 3초 이상 준다.
    page.wait_for_timeout(wait_ms)
    t = (page.title() or "").strip()
    if t in _BLOCKED_TITLES or "Access Denied" in t:
        return Attempt(status="blocked", message=f"차단 (title={t!r})")
    d = page.evaluate(_DETAIL_JS)
    return Attempt(status=classify_detail(d), data=d, message=_detail_note(d))


def _bk_browser_mobile(page, pid: str):
    """
    모바일 웹(m.coupang.com). 데스크톱과 다른 경로라 차단 정책도 다를 수 있다 — 미검증.

    _DETAIL_JS 는 본문 텍스트 정규식과 CDN URL 패턴 위주라 레이아웃이 달라도
    상당 부분 그대로 먹는다. 다만 별점은 데스크톱 전용 셀렉터
    ([class*="rating-star-num"]) 라 0 으로 나올 수 있고, 그건 partial 사유가
    아니다(가격·이미지만 보면 된다).
    """
    return _bk_browser(page, f"https://m.coupang.com/vm/products/{pid}", wait_ms=3600)


# ── 백엔드 3: Jina Reader 프록시 ─────────────────────────────────

_JINA_PRICE_RE = re.compile(r"(\d{1,2})%\s+([\d,]{3,})원[\s\S]{0,80}?([\d,]{4,})원")
_JINA_IMG_RE = re.compile(r"!\[[^\]]*\]\((https?://[^)\s]+)\)")


def _bk_jina(url: str, timeout: int = 45):
    """
    r.jina.ai 가 대신 렌더링한 마크다운을 파싱한다.

    주의 — 상품 URL 이 외부 서비스(Jina)로 나간다. 공개 상품 페이지 주소라
    민감정보는 아니지만, 외부 경유가 싫으면 DETAIL_BACKENDS 에서 빼면 된다.
    무료 티어라 레이트리밋이 있고, 텍스트 렌더링이라 스펙 표는 못 건진다.
    """
    try:
        import requests
    except ImportError:
        return None                      # 미설치 — 후보에서 제외

    r = requests.get("https://r.jina.ai/" + url,
                     headers={"User-Agent": UA, "Accept": "text/plain"},
                     timeout=timeout)
    if r.status_code != 200:
        return Attempt(status="error", message=f"HTTP {r.status_code}")
    text = r.text
    if "사용권한이 없습니다" in text or len(text) < 400:
        return Attempt(status="blocked", message=f"본문 {len(text)}자 — 차단 응답으로 보임")

    title = ""
    mt = re.search(r"^Title:\s*(.+)$", text, re.M)
    if mt:
        title = mt.group(1).strip()
        title = re.sub(r"\s*[-|]\s*쿠팡!?\s*$", "", title)

    # 호스트 뒤 숫자 필수 허용(thumbnail6/image7). _DETAIL_JS 와 같은 패턴을 쓴다.
    urls = _JINA_IMG_RE.findall(text)
    # displayitem 은 쿠팡 공통 광고 배너다(위 _DETAIL_JS 주석 참고). 제외한다.
    detail_imgs = [u for u in urls
                   if re.search(r"image\d*\.coupangcdn\.com/image/vendor_inventory", u)]
    thumbs = [hi_res(u) for u in urls
              if re.search(r"thumbnail\d*\.coupangcdn\.com/thumbnails/remote/\d+x\d+ex/", u)
              and not re.search(r"logo|icon|badge|sprite", u, re.I)]

    def _num(s):
        m = re.search(r"\d+", str(s or "").replace(",", ""))
        return int(m.group()) if m else 0

    disc = cur = org = 0
    pm = _JINA_PRICE_RE.search(text)
    if pm:
        disc, cur, org = int(pm.group(1)), _num(pm.group(2)), _num(pm.group(3))
        if org and cur and org < cur:
            org, cur = cur, org

    mr = re.search(r"([\d,]+)\s*개\s*상품평", text)
    mb = re.search(r"(한 달간 [^\n]{2,40}구매했어요)", text)

    d = {
        "title": title, "brand": "", "category": "",
        "review_count": _num(mr.group(1)) if mr else 0,
        "rating": 0,                                   # 별 너비 기반이라 텍스트에 안 남는다
        "monthly_buyers": mb.group(1) if mb else "",
        "delivery_info": "",
        "discount_rate": disc, "original_price": org, "current_price": cur,
        "detail_images": list(dict.fromkeys(detail_imgs))[:20],
        "thumbnails": list(dict.fromkeys(thumbs))[:12],
        "specs": {},
    }
    return Attempt(status=classify_detail(d), data=d, message=_detail_note(d))


# ── 라우터 진입점 ───────────────────────────────────────────────

def fetch_detail(url_or_id: str, page=None, verbose: bool = True):
    """
    상세 데이터를 후보 경로 순서대로 시도해 가져온다. 반환: (data|None, attempts)

    page 를 주면 이미 워밍업된 세션을 재사용한다(collect_full / enrich_details).
    None 이면 브라우저 백엔드는 후보에서 빠지고 jina-reader 만 남는다.
    """
    pid, url = parse_product_url(url_or_id)

    handlers = {
        "browser-desktop": lambda: _bk_browser(page, url),
        "browser-mobile": lambda: _bk_browser_mobile(page, pid),
        "jina-reader": lambda: _bk_jina(url),
    }

    def _log(att):
        if verbose:
            print(f"    · {att}")

    attempts = run_chain(DETAIL_BACKENDS, handlers,
                         env_var=DETAIL_BACKEND_ENV, on_attempt=_log)
    chosen = pick(attempts)
    if chosen is None:
        return None, attempts

    d = dict(chosen.data)
    d["_backend"] = chosen.backend
    d["_status"] = chosen.status
    return d, attempts


def normalize_detail(d: dict, pid: str, url: str) -> dict:
    """수집한 상세 데이터를 DB 저장 형태로 다듬는다(백엔드 공통)."""
    # 평점 환산은 _DETAIL_JS 안에서 끝낸다(별 너비 % ÷ 20). 5점을 넘으면 버린다.
    if not (0 < (d.get("rating") or 0) <= 5):
        d["rating"] = 0

    d["product_id"] = pid
    d["detail_url"] = url
    d["affiliate_url"] = url
    d["thumbnails"] = [hi_res(u) for u in d.get("thumbnails", [])]
    # 릴스 소재: 상세 설명 이미지 우선, 부족하면 갤러리 썸네일로 채운다
    imgs = list(dict.fromkeys(d.get("detail_images", []) + d["thumbnails"]))
    d["detail_images"] = imgs
    d["image_url"] = imgs[0] if imgs else ""
    d["is_rocket"] = "로켓" in (d.get("delivery_info") or "")

    if d.get("original_price") and d.get("current_price") and not d.get("discount_rate"):
        if d["original_price"] > d["current_price"]:
            d["discount_rate"] = round((1 - d["current_price"] / d["original_price"]) * 100)

    return d


def collect_detail(url_or_id: str, headless: bool = False) -> dict:
    """단일 상품의 상세를 수집한다. 모든 백엔드가 실패하면 예외를 던진다."""
    from playwright.sync_api import sync_playwright

    pid, url = parse_product_url(url_or_id)
    print(f"[상세] {pid} 수집 중...")

    with sync_playwright() as pw:
        browser, ctx = _new_context(pw, headless)
        try:
            page = ctx.new_page()
            _warmup(page, ctx)
            d, attempts = fetch_detail(url, page=page)
        finally:
            ctx.close()
            browser.close()

    if d is None:
        raise RuntimeError(f"상세 수집 실패 — {summarize(attempts)}")

    d = normalize_detail(d, pid, url)
    print(f"[상세] '{d['title'][:34]}' — {_detail_note(d)} "
          f"({d['_backend']}/{d['_status']})")
    return d


# ════════════════════════════════════════════════════════════════
# 3) 목록 + 상세 통합
# ════════════════════════════════════════════════════════════════

def collect_full(limit: int = 20, headless: bool = False) -> list:
    """목록을 수집한 뒤 각 상품의 상세페이지까지 방문해 릴스 소재를 채운다."""
    listing = collect_goldbox(limit=limit, headless=headless)
    from playwright.sync_api import sync_playwright

    out = []
    with sync_playwright() as pw:
        browser, ctx = _new_context(pw, headless)
        page = ctx.new_page()
        _warmup(page, ctx)
        try:
            for i, item in enumerate(listing, 1):
                try:
                    d, attempts = fetch_detail(item["detail_url"], page=page, verbose=False)
                    if d is None:
                        raise RuntimeError(summarize(attempts))

                    merged = dict(item)
                    # 상세에만 있는 값은 덧붙이고, 목록에 없던 값은 채운다.
                    for k in ("brand", "category", "monthly_buyers", "delivery_info", "specs"):
                        if d.get(k):
                            merged[k] = d[k]
                    # 평점은 상세가 더 정밀하다(목록은 0.5 단위로 뭉뚱그려져 대부분 5.0).
                    if 0 < (d.get("rating") or 0) <= 5:
                        merged["rating"] = d["rating"]
                    # 가격은 목록 값을 우선한다. 상세는 옵션가가 섞여 잘못 잡힐 수 있어
                    # 목록에 값이 없을 때만 채운다.
                    for k in ("original_price", "current_price", "discount_rate"):
                        if not merged.get(k) and d.get(k):
                            merged[k] = d[k]
                    thumbs = [hi_res(u) for u in d.get("thumbnails", [])]
                    imgs = list(dict.fromkeys(d.get("detail_images", []) + thumbs))
                    if imgs:
                        merged["detail_images"] = imgs
                        merged["thumbnails"] = thumbs
                        merged["image_url"] = merged.get("image_url") or imgs[0]
                    if d.get("review_count"):
                        merged["review_count"] = d["review_count"]
                    out.append(merged)
                    print(f"  [{i}/{len(listing)}] {merged['title'][:32]} — "
                          f"이미지 {len(merged.get('detail_images', []))}장 "
                          f"({d['_backend']}/{d['_status']})")
                except Exception as e:
                    print(f"  [{i}/{len(listing)}] 실패: {str(e)[:70]}")
                    out.append(item)
                time.sleep(random.uniform(0.8, 1.8))   # 레이트리밋 회피
        finally:
            ctx.close()
            browser.close()
    return out


# ════════════════════════════════════════════════════════════════

def pending_detail(limit: int = 5) -> list:
    """상세 보강이 아직 안 된 상품을 고른다(상세 이미지가 2장 미만인 것)."""
    migrate_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT product_id, title, detail_url, detail_images
        FROM products
        WHERE is_real=1 AND detail_url<>''
        ORDER BY discount_rate DESC
    """).fetchall()
    conn.close()
    out = []
    for r in rows:
        try:
            imgs = json.loads(r["detail_images"] or "[]")
        except Exception:
            imgs = []
        if len(imgs) < 2:
            out.append(dict(r))
        if len(out) >= limit:
            break
    return out


def enrich_details(limit: int = 5, delay_range=(25, 45), headless: bool = False) -> int:
    """
    상세페이지를 조금씩 나눠 보강한다.

    쿠팡은 짧은 시간에 상세페이지를 여러 번 열면 곧바로 막는다(실측: 몇 건 뒤 차단).
    그래서 한 번에 다 긁지 않고, 요청 간격을 넉넉히 두고 소량씩 채운다.
    연속 2회 차단되면 즉시 중단한다 — 계속 두드리면 차단이 길어진다.
    반복 실행하면 DB 가 점진적으로 채워진다.
    """
    from playwright.sync_api import sync_playwright

    targets = pending_detail(limit)
    if not targets:
        print("[보강] 상세가 필요한 상품이 없습니다.")
        return 0
    print(f"[보강] 대상 {len(targets)}건 (요청 간격 {delay_range[0]}~{delay_range[1]}초)")

    done, blocked_streak = 0, 0
    with sync_playwright() as pw:
        browser, ctx = _new_context(pw, headless)
        page = ctx.new_page()
        _warmup(page, ctx)
        try:
            for i, t in enumerate(targets, 1):
                try:
                    d, attempts = fetch_detail(t["detail_url"], page=page, verbose=False)
                    if d is None:
                        # 후보 경로를 전부 써 보고도 못 얻었을 때만 '차단'으로 센다.
                        # 데스크톱 한 번 막혔다고 중단하면 나머지 경로를 못 써 본다.
                        blocked_streak += 1
                        print(f"  [{i}/{len(targets)}] 전 경로 실패 — {t['title'][:26]} "
                              f"| {summarize(attempts)}")
                        if blocked_streak >= 2:
                            print("  연속 2회 실패. 중단합니다. 시간을 두고 다시 실행하세요.")
                            break
                        page.wait_for_timeout(int(random.uniform(30, 60) * 1000))
                        continue

                    blocked_streak = 0
                    thumbs = [hi_res(u) for u in d.get("thumbnails", [])]
                    imgs = list(dict.fromkeys(d.get("detail_images", []) + thumbs))

                    rec = {"product_id": t["product_id"], "title": d.get("title") or t["title"],
                           "detail_url": t["detail_url"], "affiliate_url": t["detail_url"],
                           "detail_images": imgs, "thumbnails": thumbs}
                    for k in ("brand", "category", "monthly_buyers", "delivery_info",
                              "review_count", "specs"):
                        if d.get(k):
                            rec[k] = d[k]
                    if 0 < (d.get("rating") or 0) <= 5:
                        rec["rating"] = d["rating"]
                    # 가격은 목록 값이 더 안전하다 — 여기서는 건드리지 않는다(가드가 보호).
                    save_real_products([rec])
                    done += 1
                    # 상태를 그대로 찍는다. partial 을 OK 로 보고하면 '수집됐다'고 착각하게 된다.
                    print(f"  [{i}/{len(targets)}] {d['_status'].upper()} {t['title'][:28]} — "
                          f"이미지 {len(imgs)}장, 리뷰 {d.get('review_count', 0):,} "
                          f"({d['_backend']})")
                except Exception as e:
                    print(f"  [{i}/{len(targets)}] 실패: {str(e)[:70]}")
                if i < len(targets):
                    page.wait_for_timeout(int(random.uniform(*delay_range) * 1000))
        finally:
            ctx.close()
            browser.close()
    print(f"[보강] {done}건 완료")
    return done


def doctor() -> dict:
    """
    환경과 백엔드 후보를 점검한다. **수집은 하지 않는다.**

    쿠팡 페이지를 열어 보지 않는 게 핵심이다. '살아 있나' 확인하려고 두드리는 순간
    그것도 요청 한 번이고, 상세는 두드릴수록 차단이 길어진다. 그래서 여기서는
    설치 여부·DB 상태·후보 순서만 본다. 실제 가용성은 enrich 를 한 번 돌려
    거기 찍히는 백엔드/상태로 판단한다.
    """
    from backend_router import ordered_backends

    print("═" * 60)
    print("쿠팡 수집기 진단 (수집 없음)")
    print("═" * 60)

    report = {}

    # 1) 파이썬 의존성 — import 가 되는지까지 본다(설치 목록에 있다 ≠ 쓸 수 있다)
    for mod, why in (("playwright", "브라우저 백엔드 2종"), ("requests", "jina-reader 백엔드")):
        try:
            __import__(mod)
            report[mod] = "ok"
            print(f"  [OK]   {mod:<12} — {why}")
        except ImportError as e:
            report[mod] = "missing"
            print(f"  [X]    {mod:<12} — 미설치 ({e}). 해당 백엔드는 후보에서 제외된다")

    # 2) Chromium 실물. playwright 패키지가 있어도 브라우저를 안 받았으면 못 뜬다.
    #    pw.chromium.executable_path 를 쓰면 정확하지만 Node 드라이버가 뜨고,
    #    종료할 때 TargetClosedError 를 콘솔에 뱉는다(Windows). 진단은 조용해야
    #    하므로 설치 디렉터리를 직접 훑는다 — 프로세스를 하나도 띄우지 않는다.
    if report.get("playwright") == "ok":
        import glob as _glob
        roots = [os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or "",
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "ms-playwright"),
                 os.path.expanduser("~/.cache/ms-playwright")]
        hits = []
        for root in filter(None, roots):
            hits += _glob.glob(os.path.join(root, "chromium-*", "chrome-win*", "chrome.exe"))
            hits += _glob.glob(os.path.join(root, "chromium-*", "chrome-linux", "chrome"))
            hits += _glob.glob(os.path.join(root, "chromium-*", "chrome-mac", "**", "Chromium"),
                               recursive=True)
        # 빌드가 여러 개 남아 있으면 최신 것을 보여준다(실제로 쓰이는 건 그쪽이다)
        hits.sort(reverse=True)
        report["chromium"] = "ok" if hits else "missing"
        print(f"  [{'OK' if hits else 'X':<2}]   chromium     — "
              + (f"{hits[0]}" + (f"  (빌드 {len(hits)}개)" if len(hits) > 1 else "")
                 if hits else "실행파일 없음. `playwright install chromium`"))

    # 3) 상세 백엔드 우선순위 (override 반영된 실제 순서)
    override = os.environ.get(DETAIL_BACKEND_ENV, "").strip()
    order = ordered_backends(DETAIL_BACKENDS, env_var=DETAIL_BACKEND_ENV)
    print(f"\n  상세 백엔드 순서: {' → '.join(order)}")
    if override:
        note = "적용됨" if order and order[0].startswith(override) else "무시됨(모르는 이름)"
        print(f"    {DETAIL_BACKEND_ENV}={override} → {note}")
    print("    ※ 실제 가용성은 여기서 확인하지 않는다 — 확인 자체가 요청이라서다.")
    report["detail_backends"] = order

    # 4) DB
    try:
        migrate_db()
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        real = cur.execute("SELECT COUNT(*) FROM products WHERE is_real=1").fetchone()[0]
        dummy = cur.execute(
            "SELECT COUNT(*) FROM products WHERE is_real IS NULL OR is_real=0").fetchone()[0]
        conn.close()
        pend = len(pending_detail(limit=10**6))
        report.update(real=real, dummy=dummy, pending=pend)
        print(f"\n  DB: 실측 {real}건 / 더미 {dummy}건 / 상세 보강 대기 {pend}건")
        if pend:
            print(f"    → python coupang_live_collector.py enrich 5")
    except Exception as e:
        report["db"] = f"error: {e}"
        print(f"\n  [X] DB 접근 실패: {str(e)[:80]}")

    print("═" * 60)
    return report


def set_affiliate_link(product_id: str, url: str) -> bool:
    """
    파트너스 딥링크를 수동으로 넣는다.

    수집기가 저장하는 affiliate_url 은 그냥 상품 페이지 주소라 추적 코드가 없다.
    그 상태로 글을 발행하면 방문자가 사서도 쿠팡이 누가 보냈는지 알 수 없어
    수수료가 0원이다. 파트너스에서 만든 https://link.coupang.com/a/XXXX 를 넣어야 한다.
    """
    u = (url or "").strip()
    if "link.coupang.com" not in u:
        raise ValueError(
            f"파트너스 딥링크가 아닙니다: {u[:60]}\n"
            "  https://link.coupang.com/a/... 형태여야 수수료가 붙습니다."
        )
    migrate_db()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    n = cur.execute("UPDATE products SET affiliate_url=? WHERE product_id=?",
                    (u, str(product_id))).rowcount
    conn.commit()
    conn.close()
    if n:
        print(f"[링크] {product_id} → {u}")
    else:
        print(f"[링크] 상품 {product_id} 을(를) DB 에서 찾지 못했습니다.")
    return bool(n)


def _summary():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    real = cur.execute("SELECT COUNT(*) FROM products WHERE is_real=1").fetchone()[0]
    dummy = cur.execute("SELECT COUNT(*) FROM products WHERE is_real IS NULL OR is_real=0").fetchone()[0]
    print(f"\nDB 현황 — 실측 {real}건 / 더미 {dummy}건")
    for r in cur.execute("""SELECT title, discount_rate, original_price, current_price, review_count
                            FROM products WHERE is_real=1 ORDER BY discount_rate DESC LIMIT 5"""):
        print(f"  {r['discount_rate']:>3}%  {r['original_price']:>8,} -> {r['current_price']:>8,}  "
              f"리뷰 {r['review_count']:>6,}  {r['title'][:38]}")
    conn.close()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"

    if cmd == "doctor":
        doctor()
        sys.exit(0)

    added = migrate_db()
    if added:
        print(f"[DB] 컬럼 추가: {', '.join(added)}")

    if cmd == "list":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
        items = collect_goldbox(limit=n)
        print(f"[DB] {save_real_products(items)}건 저장")
        _summary()

    elif cmd == "full":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        items = collect_full(limit=n)
        print(f"[DB] {save_real_products(items)}건 저장")
        _summary()

    elif cmd == "setlink":
        if len(sys.argv) < 4:
            print("사용법: python coupang_live_collector.py setlink <상품ID> <파트너스 딥링크>")
            sys.exit(1)
        set_affiliate_link(sys.argv[2], sys.argv[3])

    elif cmd == "enrich":
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        enrich_details(limit=n)
        _summary()

    elif cmd == "detail":
        if len(sys.argv) < 3:
            print("사용법: python coupang_live_collector.py detail <상품URL 또는 상품ID>")
            sys.exit(1)
        d = collect_detail(sys.argv[2])
        print(json.dumps({k: v for k, v in d.items() if k != "specs"},
                         ensure_ascii=False, indent=2)[:2000])
        print(f"[DB] {save_real_products([d])}건 저장")

    else:
        print(__doc__)
