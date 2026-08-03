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
from threads.reply_writer import _cp949_safe

# 카드 자신의 permalink 는 "/@handle/post/id 링크가 <time datetime> 을
# 바로 감싼다"는 짝으로 식별한다(리뷰 Finding 2) — 첫 번째 /post/ 링크를
# 그냥 집으면 본문 속 멘션 링크("...@누구 얘기 좀 그만해...")가 카드
# 자신의 글보다 먼저 나와 그걸 permalink 로 오인하고, 그 오인된 URL에
# 이 카드의 (실제로는 다른 사람의) 본문·시각이 잘못 붙는다 — 이 모듈이
# 낼 수 있는 사고 중 가장 나쁜 것(엉뚱한 글 URL 아래 답글이 달림)이라
# 위치가 아니라 구조(자신의 <time> 을 직접 감싸는 링크)로 못박는다.
# 프래그먼트(#...)는 URL 에서 제외한다(Finding 5) — 안 하면 같은 글이
# #comment-1 / #comment-2 처럼 프래그먼트만 다르게 나올 때 dedup 이
# 뚫린다.
_PERMALINK_RE = re.compile(
    r'<a\s+href="(/@([^/"]+)/post/([^"?#]+))(?:[?#][^"]*)?"[^>]*>'
    r'\s*<time[^>]*datetime="([^"]+)"')

# Threads 가 dir="auto" 스팬으로 함께 내보내는 것으로 실측된 UI 문구.
# 실제 작성자 글이 아니라 버튼/라벨이라 본문에 섞이면 안 된다.
# ⚠ 전수 목록이 아니다 — 알려진 것만 걸러낸다. Threads 가 새 문구를
# 쓰거나 다른 언어로 표시하면 그건 못 걸러낸다(리뷰 Finding 5, 잔여
# 위험으로 기록 — task-4-report.md "실측 체크리스트" 참고).
_UI_CHROME = {"번역 보기", "더 보기", "더보기", "See translation", "See more"}

# 한 카드 안에서 permalink+<time> 짝을 못 하나로 못 좁힌 카드 수
# (직전 parse_feed() 호출 기준). 인용/리포스트처럼 카드가 중첩되면
# 바깥 글의 자기 링크가 안쪽 청크로 흘러들어가 짝이 2개 잡힌다(Finding
# 3) — 어느 게 진짜 이 카드 것인지 문자열만으로는 확정할 수 없으므로
# 오귀속시키느니 버리고 셈만 남긴다. parse_feed() 의 반환 타입은
# Task 6 이 의존하므로 바꾸지 않고, 별도 접근자로 노출한다.
_last_dropped = 0


def last_dropped_count() -> int:
    """가장 최근 parse_feed() 호출에서 확정 못 해 버린 카드 수."""
    return _last_dropped


def parse_feed(html: str) -> list:
    """피드 HTML 에서 글 목록을 뽑는다. 못 뽑으면 빈 목록(예외 아님).

    빈 목록으로 돌려주는 이유 — 예외로 죽으면 runner 가 멈추지만,
    빈 목록이면 '3회 연속 0건 → 자동 강등' 로직이 받아 처리한다."""
    global _last_dropped
    _last_dropped = 0
    if not html:
        return []
    try:
        return _parse(html)
    except Exception:
        return []


def _parse(html: str) -> list:
    from html import unescape
    global _last_dropped

    posts, seen = [], set()
    # 글 카드 단위로 자른다.
    chunks = html.split('data-pressable-container="true"')[1:]
    for chunk in chunks:
        matches = list(_PERMALINK_RE.finditer(chunk))
        if not matches:
            continue
        if len(matches) > 1:
            # 이 청크 안에서 "카드 자신의 글"을 구조만으로 못 좁혔다.
            # 중첩 카드(인용/리포스트)의 전형적인 증상 — 버리고 셈만 남긴다.
            _last_dropped += 1
            continue
        m = matches[0]
        path, handle, _pid, posted_at = m.group(1), m.group(2), m.group(3), m.group(4)
        url = THREADS_HOME + path
        if url in seen:
            continue
        seen.add(url)

        # dir="auto" 스팬들이 본문. 여러 조각으로 쪼개져 오므로 이어 붙인다.
        # 단, 알려진 UI 문구(번역 보기 등)는 본문이 아니므로 걸러낸다.
        parts = re.findall(r'<span[^>]*dir="auto"[^>]*>(.*?)</span>', chunk, re.DOTALL)
        cleaned = []
        for p in parts:
            t = unescape(re.sub(r"<[^>]+>", "", p)).strip()
            if t and t not in _UI_CHROME:
                cleaned.append(t)
        text = re.sub(r"\s{2,}", " ", " ".join(cleaned)).strip()

        posts.append(RawPost(url=url, author=f"@{handle}",
                             text=text, posted_at=posted_at))
    return posts


def harvest(account: str = "", limit: int = 0, headless: bool = True) -> list:
    """추천 피드를 스크롤하며 limit 건까지 모은다.

    로그인 실패 시 빈 목록을 준다(예외 아님). 호출부가 '수집 0건'과
    같은 경로로 다루면 되고, 로그인 상태는 preflight 에서 따로 본다.

    ⚠ 리뷰 Finding 1: 어떤 단계에서 드라이버가 죽어도(threads.net SPA
    상대로 TimeoutException 은 실전에서 충분히 있을 수 있다) 예외를
    밖으로 흘리지 않는다 — 시작 전에 죽으면 빈 목록, 스크롤 도중에
    죽으면 그때까지 모은 것을 그대로 돌려준다. 조용히 삼키지는 않고
    원인을 진단 메시지로 남긴다(콘솔에 나가는 값이라 _cp949_safe 를
    거친다 — 드라이버 예외 메시지에 페이지에서 온 텍스트가 섞여
    나올 가능성을 배제할 수 없다)."""
    limit = limit or config.THREADS_HARVEST_LIMIT
    auto = ThreadsAutomator(account, headless=headless)
    try:
        try:
            if not auto.load_session():
                print("[threads:harvest] 세션 없음/만료 - python login.py threads 필요")
                return []
            auto.driver.get(THREADS_HOME)
            time.sleep(3)
        except Exception as e:
            msg = _cp949_safe(str(e))[:160]
            print(f"[threads:harvest] 시작 단계 오류 - {msg}")
            return []

        collected, stale_rounds = {}, 0
        for _ in range(20):                      # 스크롤 상한 (무한루프 방지)
            try:
                for p in parse_feed(auto.driver.page_source):
                    collected.setdefault(p.url, p)
                if len(collected) >= limit:
                    break
                before = len(collected)
                auto.driver.execute_script("window.scrollBy(0, window.innerHeight*2)")
                time.sleep(2)
                stale_rounds = stale_rounds + 1 if len(collected) == before else 0
                if stale_rounds >= 3:            # 더 안 늘면 그만
                    break
            except Exception as e:
                # 스크롤 도중 죽어도 지금까지 모은 건 살린다 — 통째로
                # 버리는 것보다 부분 수집이 낫다(gate 는 이미 판정된
                # 글만 다루므로 부분 수집이 섞여도 안전).
                msg = _cp949_safe(str(e))[:160]
                print(f"[threads:harvest] 수집 중 오류 - {msg} "
                      f"(지금까지 {len(collected)}건 유지)")
                break
        return list(collected.values())[:limit]
    finally:
        auto.quit()
