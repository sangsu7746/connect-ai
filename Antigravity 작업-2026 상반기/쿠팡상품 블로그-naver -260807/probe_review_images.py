"""
상품평 사진이 상세페이지 어디에 있는지 실물로 확인한다.

셀렉터를 짐작으로 쓰면 0장을 긁고도 성공한 줄 안다. 한 번 떠 보고 맞춘다.
"""
import json
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROBE_JS = r"""
async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  // 상품평은 페이지 아래쪽에 있고 lazy-load 다. 끝까지 훑어야 src 가 채워진다.
  for (let y = 0; y <= 12; y++) {
    window.scrollTo(0, document.body.scrollHeight * y / 12);
    await sleep(500);
  }
  await sleep(1500);

  const all = [...document.querySelectorAll('img')]
    .map(i => i.src || i.dataset.src || i.getAttribute('data-original') || '')
    .filter(Boolean);

  // 호스트/경로별로 몇 장씩 있는지 센다 — 어떤 패턴이 상품평인지 여기서 드러난다
  const buckets = {};
  for (const u of all) {
    const m = u.match(/https?:\/\/([^/]+)(\/[^?]*)/);
    if (!m) continue;
    const host = m[1].replace(/\d+/g, 'N');
    const path = m[2].split('/').slice(0, 4).join('/').replace(/\d{3,}/g, 'N');
    const key = host + path;
    (buckets[key] = buckets[key] || []).push(u);
  }

  // 상품평 영역 안의 img 만 따로
  const revRoot = document.querySelector(
    '#sdpReview, .sdp-review, [class*="review-list"], [class*="sdp-review"]');
  const inReview = revRoot
    ? [...revRoot.querySelectorAll('img')].map(i => i.src || i.dataset.src || '').filter(Boolean)
    : [];

  return {
    total_imgs: all.length,
    review_root: revRoot ? (revRoot.id || revRoot.className).slice(0, 60) : null,
    in_review_count: inReview.length,
    in_review_sample: [...new Set(inReview)].slice(0, 8),
    buckets: Object.fromEntries(
      Object.entries(buckets)
        .sort((a, b) => b[1].length - a[1].length)
        .slice(0, 12)
        .map(([k, v]) => [k, { n: v.length, sample: v[0] }])),
  };
}
"""


def main() -> int:
    import coupang_live_collector as C
    pid = sys.argv[1] if len(sys.argv) > 1 else "7522620409"
    url = f"https://www.coupang.com/vp/products/{pid}"

    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        # 쿠팡은 headless 와 UA 위조를 잡아낸다. 실제 창을 띄우고 locale 을 준다.
        ctx = pw.chromium.launch_persistent_context(
            os.path.join(BASE_DIR, ".coupang_profile"),
            headless=False, locale="ko-KR",
            viewport={"width": 1400, "height": 950},
            args=["--disable-blink-features=AutomationControlled"])
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        print(f"상세페이지 열기: {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        # body 가 없는 채로 JS 를 넣으면 'Cannot read properties of null' 로 죽는다.
        # 쿠팡이 봇으로 보고 빈 페이지나 차단 화면을 주는 경우가 있어 먼저 확인한다.
        try:
            page.wait_for_selector("body", timeout=20000)
        except Exception:
            pass
        state = page.evaluate("""() => ({
            url: location.href,
            title: document.title,
            hasBody: !!document.body,
            len: document.body ? document.body.innerText.length : 0,
            head: document.body ? document.body.innerText.slice(0, 200) : ''
        })""")
        print(f"  실제 주소: {state['url']}")
        print(f"  제목     : {state['title']}")
        print(f"  본문 길이: {state['len']}자")
        if not state["hasBody"] or state["len"] < 200:
            print(f"  본문 앞부분: {state['head']!r}")
            print("\n⛔ 상품 페이지가 아닙니다(차단이거나 로딩 실패).")
            print("   창을 60초 열어 둡니다 — 사람이 직접 확인해 주세요.")
            page.wait_for_timeout(60000)
            state = page.evaluate("""() => ({url: location.href,
                len: document.body ? document.body.innerText.length : 0})""")
            print(f"   다시 확인: {state['url']} · {state['len']}자")
            if state["len"] < 200:
                ctx.close()
                return 1

        info = page.evaluate(PROBE_JS)
        print(f"\n페이지 전체 img: {info['total_imgs']}장")
        print(f"상품평 컨테이너: {info['review_root']}")
        print(f"그 안의 img: {info['in_review_count']}장")
        for u in info["in_review_sample"]:
            print(f"    {u[:110]}")
        print("\n경로 패턴별 개수:")
        for k, v in info["buckets"].items():
            print(f"  {v['n']:4}장  {k}")
            print(f"          {v['sample'][:100]}")

        out = os.path.join(BASE_DIR, "logs", "review_probe.json")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        open(out, "w", encoding="utf-8").write(
            json.dumps(info, ensure_ascii=False, indent=2))
        print(f"\n저장: {out}")
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
