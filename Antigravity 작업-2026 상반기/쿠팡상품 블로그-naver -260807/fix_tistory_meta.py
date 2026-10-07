"""
이미 발행된 티스토리 글의 제목과 카테고리를 바로잡는다. 본문은 건드리지 않는다.

고치는 것 두 가지 (로그인 1회):
  1. 제목에서 "[광고]" 제거
     파트너스 기준은 '제목 또는 게시물 첫 부분' 중 하나면 된다. 이 시스템은 대가성 고지를
     본문 맨 위에 넣으므로 제목 표시는 불필요하고, 40자 제한을 4자 아끼는 편이 낫다.
  2. 카테고리 지정
     상세 수집이 안 된 상품이 기본값('쿠팡 할인물품')으로 떨어졌는데 티스토리에는
     그 분류가 없어서 4건이 '카테고리 없음' 으로 발행됐다.
"""
import os
import re
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import tistory_poster as T
import coupang_blog_pipeline as P
from fix_tistory_images import published_entries, match_product, log


def _fetch_title(entry_id: int) -> str:
    """공개 페이지에서 제목만 읽는다. RSS 가 최신 10건만 주기 때문에 필요하다."""
    import urllib.request
    url = f"https://{T.BLOG}.tistory.com/{entry_id}"
    try:
        h = urllib.request.urlopen(urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; KakaoTalk-Scrap/1.0)"}),
            timeout=15).read().decode("utf-8", "ignore")
    except Exception:
        return ""
    m = re.search(r'property=["\']og:title["\'][^>]*content=["\']([^"\']+)', h)
    return m.group(1).strip() if m else ""


def main() -> int:
    limit = 10
    for a in sys.argv[1:]:
        if a.isdigit():
            limit = int(a)

    # RSS 는 최신 10건만 준다. 그보다 앞 글의 제목은 공개 페이지에서 직접 읽는다
    # (제목을 알아야 상품을 특정하고 카테고리를 정할 수 있다).
    entries = published_entries()
    known = {e["id"] for e in entries}
    lo = min(known) if known else 1
    for i in range(1, lo):
        t = _fetch_title(i)
        if t:
            entries.append({"id": i, "title": t})
    entries.sort(key=lambda e: -e["id"])
    entries = entries[:limit]
    log("=" * 60)
    log(f"티스토리 제목·카테고리 정리 — 대상 {len(entries)}건")

    jobs = {}
    for e in entries:
        prod = match_product(e["title"])
        if not prod:
            log(f"  ? /{e['id']} 상품 못 찾음 — 제목만 정리: {e['title'][:40]}")
            cat = ""
        else:
            cat = T.to_tistory_category(P.map_blog_category(prod))

        new_title = P.ad_title(e["title"])
        changed_title = new_title != e["title"]
        log(f"  /{e['id']:>2}  {'제목수정' if changed_title else '제목유지'} · "
            f"카테고리 '{cat or '(그대로)'}'")
        if changed_title:
            log(f"        {e['title'][:44]}")
            log(f"     → {new_title[:44]}")

        if not changed_title and not cat:
            continue

        # 본문은 그대로 두고 제목만 바꾼다
        jobs[e["id"]] = {
            "transform": (lambda t, h: (P.ad_title(t), h)),
            "category": cat,
        }

    if not jobs:
        log("\n바꿀 것이 없습니다.")
        return 0

    log("")
    log("─" * 60)
    log(f"  {len(jobs)}건을 고칩니다. 브라우저가 열리면 티스토리(카카오)에 로그인해 주세요.")
    log("  비밀번호는 이 스크립트가 다루지 않습니다.")
    log("─" * 60)

    res = T.edit_posts(jobs, mode="public", log=log, wait_minutes=12.0)

    ok = 0
    for eid, r in sorted(res.items()):
        if r.get("ok"):
            ok += 1
            log(f"  ✅ /{eid} {r.get('note','')}"
                + (f" · 카테고리 {'적용' if r.get('category_ok') else '실패'}"
                   if "category_ok" in r else ""))
        else:
            log(f"  ✘ /{eid} {r.get('why') or r.get('note')}")
    log("")
    log("=" * 60)
    log(f"정리 완료 {ok}/{len(jobs)}건")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
