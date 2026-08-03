# ============================================================
#  threads/harvester.py — 추천 피드 수집
#  · parse_feed() 는 브라우저를 모르는 순수 함수 → 픽스처로 테스트.
#  · 셀렉터는 난독화된 클래스명이 아니라 구조·속성에 건다.
#    (Meta 는 클래스명을 수시로 바꾸지만 role/href/datetime 은 오래간다)
# ============================================================
from __future__ import annotations

import re
import time

import config
from threads.automator import THREADS_HOME, ThreadsAutomator
from threads.models import RawPost

# /@handle/post/XXXX 형태의 링크가 글 1건의 고유 주소다.
_POST_HREF_RE = re.compile(r'href="(/@([^/"]+)/post/([^"?]+))"')


def parse_feed(html: str) -> list:
    """피드 HTML 에서 글 목록을 뽑는다. 못 뽑으면 빈 목록(예외 아님).

    빈 목록으로 돌려주는 이유 — 예외로 죽으면 runner 가 멈추지만,
    빈 목록이면 '3회 연속 0건 → 자동 강등' 로직이 받아 처리한다."""
    if not html:
        return []
    try:
        return _parse(html)
    except Exception:
        return []


def _parse(html: str) -> list:
    from html import unescape

    posts, seen = [], set()
    # 글 카드 단위로 자른다.
    chunks = html.split('data-pressable-container="true"')[1:]
    for chunk in chunks:
        m = _POST_HREF_RE.search(chunk)
        if not m:
            continue
        path, handle, _pid = m.group(1), m.group(2), m.group(3)
        url = THREADS_HOME + path
        if url in seen:
            continue
        seen.add(url)

        tm = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        posted_at = tm.group(1) if tm else ""

        # dir="auto" 스팬들이 본문. 여러 조각으로 쪼개져 오므로 이어 붙인다.
        parts = re.findall(r'<span[^>]*dir="auto"[^>]*>(.*?)</span>', chunk, re.DOTALL)
        text = " ".join(unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts)
        text = re.sub(r"\s{2,}", " ", text).strip()

        posts.append(RawPost(url=url, author=f"@{handle}",
                             text=text, posted_at=posted_at))
    return posts


def harvest(account: str = "", limit: int = 0, headless: bool = True) -> list:
    """추천 피드를 스크롤하며 limit 건까지 모은다.

    로그인 실패 시 빈 목록을 준다(예외 아님). 호출부가 '수집 0건'과
    같은 경로로 다루면 되고, 로그인 상태는 preflight 에서 따로 본다."""
    limit = limit or config.THREADS_HARVEST_LIMIT
    auto = ThreadsAutomator(account, headless=headless)
    try:
        if not auto.load_session():
            print("[threads:harvest] 세션 없음/만료 - python login.py threads 필요")
            return []
        auto.driver.get(THREADS_HOME)
        time.sleep(3)

        collected, stale_rounds = {}, 0
        for _ in range(20):                      # 스크롤 상한 (무한루프 방지)
            for p in parse_feed(auto.driver.page_source):
                collected.setdefault(p.url, p)
            if len(collected) >= limit:
                break
            before = len(collected)
            auto.driver.execute_script("window.scrollBy(0, window.innerHeight*2)")
            time.sleep(2)
            stale_rounds = stale_rounds + 1 if len(collected) == before else 0
            if stale_rounds >= 3:                # 더 안 늘면 그만
                break
        return list(collected.values())[:limit]
    finally:
        auto.quit()
