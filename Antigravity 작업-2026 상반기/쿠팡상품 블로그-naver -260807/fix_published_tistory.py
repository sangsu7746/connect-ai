"""
이미 발행된 티스토리 글을 파트너스 승인 기준에 맞게 고친다.

왜 필요한가: 파트너스 최종 승인이 반려됐고 사유가 "대가성 문구는 활동 게시물 최상단"이다.
심사자는 코드가 아니라 실제로 발행된 글을 본다. 코드만 고쳐서는 재승인이 안 된다.

고치는 것 세 가지:
  1. 제목 앞에 [광고]
  2. 대가성 고지를 본문 최상단으로 (기존 글은 1만 자 뒤에 회색 작은 글씨로 있었다)
  3. 구매 링크를 파트너스 딥링크로 (추적 코드가 없으면 수수료가 0원이다)
"""
import sys
import sqlite3

sys.path.insert(0, r"D:\Antigravity 작업-2026 상반기\쿠팡상품 블로그-naver -260807")
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import tistory_poster as T
import coupang_blog_pipeline as P
import guardrails as G

DISCLOSURE = P.PARTNERS_DISCLOSURE

#: 티스토리 글 번호 → DB 상품 ID. 딥링크를 붙이려면 어느 상품인지 알아야 한다.
ENTRY_TO_PRODUCT = {
    1: "8982016972",   # 데오람 미니 드라이버 8종 세트
    2: "8336040965",   # 미샤 소프트 면봉
}


def deeplink_for(product_id: str) -> str:
    conn = sqlite3.connect(P.os.path.join(P.BASE_DIR, "price_history.db"))
    try:
        row = conn.execute("SELECT affiliate_url FROM products WHERE product_id=?",
                           (product_id,)).fetchone()
    finally:
        conn.close()
    url = (row[0] if row else "") or ""
    return url if "link.coupang.com" in url else ""


def make_transform(deeplink: str):
    def transform(title: str, html: str):
        new_title = P.ad_title(title)
        new_html = T.fix_disclosure_html(html, DISCLOSURE)
        new_html = T.swap_affiliate(new_html, deeplink)
        return new_title, new_html
    return transform


def main() -> int:
    only = [int(x) for x in sys.argv[1:] if x.isdigit()]
    targets = {k: v for k, v in ENTRY_TO_PRODUCT.items() if not only or k in only}

    print("=" * 66)
    print("  티스토리 발행글 파트너스 기준 수정")
    print("=" * 66)

    jobs = {}
    for entry_id, pid in sorted(targets.items()):
        deep = deeplink_for(pid)
        print(f"[{entry_id}] 상품 {pid} · 딥링크 {deep or '없음(링크 유지)'}")
        jobs[entry_id] = make_transform(deep)

    # 한 세션에서 모두 처리한다. 글마다 브라우저를 새로 열면 세션이 끊긴다.
    results = T.edit_posts(jobs, mode="public")
    for entry_id, res in sorted(results.items()):
        if res.get("ok"):
            print(f"  [{entry_id}] ✅ {res.get('note')}")
        else:
            print(f"  [{entry_id}] ❌ {res.get('why') or res.get('note')}")

    # 고친 결과를 실제 공개 페이지에서 확인한다. 저장했다는 말만 믿지 않는다.
    print("\n" + "=" * 66)
    print("  공개 페이지 재확인")
    import re
    import urllib.request
    hdr = {"User-Agent": "Mozilla/5.0 (compatible; KakaoTalk-Scrap/1.0)"}
    for entry_id in sorted(targets):
        url = f"https://{T.BLOG}.tistory.com/{entry_id}"
        try:
            h = urllib.request.urlopen(
                urllib.request.Request(url, headers=hdr), timeout=20).read().decode("utf-8", "ignore")
        except Exception as e:
            print(f"  /{entry_id}  확인 실패: {str(e)[:50]}")
            continue
        t = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', h)
        title = t.group(1) if t else ""

        # 페이지 전체를 검사하면 안 된다. 테마의 헤더·사이드바에도 이미지와 링크가 있어서
        # "고지 앞에 이미지가 있다"는 오탐이 난다(실제로 그렇게 잘못 판정했다).
        # 티스토리 본문 컨테이너만 떼어내서 본다.
        m = re.search(r'<div[^>]*class="[^"]*contents_style[^"]*"[^>]*>(.*)', h, re.S)
        art = m.group(1)[:20000] if m else h
        plain = re.sub(r"<[^>]+>", " ", art)
        probs = G.check_disclosure(plain, title)
        deep_ok = "link.coupang.com" in h
        print(f"\n  /{entry_id}  {title[:44]}")
        print(f"     파트너스 기준: {'통과' if not probs else '위반 ' + str(len(probs)) + '건'}")
        for x in probs:
            print(f"       ⛔ {x}")
        print(f"     딥링크: {'있음' if deep_ok else '없음 ⛔'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
