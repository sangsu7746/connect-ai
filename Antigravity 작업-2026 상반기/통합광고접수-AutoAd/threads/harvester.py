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
# 그냥 집으면 본문 속 멘션 링크가 카드 자신의 글보다 먼저 나와 그걸
# permalink 로 오인하고, 그 오인된 URL에 이 카드의 (실제로는 다른
# 사람의) 본문·시각이 잘못 붙는다 — 이 모듈이 낼 수 있는 사고 중
# 가장 나쁜 것(엉뚱한 글 URL 아래 답글이 달림)이라 위치가 아니라
# 구조(자신의 <time> 을 직접 감싸는 링크)로 못박는다.
#
# ⚠ 리뷰 Finding 6: 앵커 여는 태그를 `<a\s+href="..."` 로 고정하면
# href 가 그 앵커의 "첫" 속성일 때만 걸린다. 실제 React 렌더링은
# role/class/aria-*/data-* 를 href 보다 먼저 내보내는 게 흔해서(리뷰어
# 재현: `<a role="link" class="x1i10hfl" href="...">`), 이 제약을 걸어둔
# 채로는 실채널에서 아무것도 못 잡으면서 last_*_count() 도 0(신호조차
# 없음)이 나올 수 있었다 — Finding 2 의 부작용.
#
# 그래서 2단계로 바꿨다: ① 앵커의 "여는 태그 전체"(`<a\s+([^>]*)>`)를
# 한 번에 잡아 그 태그 자신의 `>` 에서 멈추고(다른 앵커로 안 건너감),
# 그 바로 뒤에 `<time datetime>` 이 오는지만 구조로 확인한다.
# ② 그렇게 확정된 "카드 자신의 permalink 후보" 앵커의 속성 문자열
# 안에서만 href 를 순서 무관하게 찾는다. `[^>]*` 가 `>` 를 못 건너가는
# 성질 덕분에, 형제 앵커 A(href 만 있고 <time> 없음)의 href 가 형제
# 앵커 B 의 <time> 과 잘못 짝지어지는 일도 구조적으로 막힌다 — A 의
# 여는 태그가 끝나는 `>` 바로 뒤에 오는 건 `<time` 이 아니라(보통
# `</a>` 나 다른 내용) 이므로 A 위치에서는 애초에 매치 자체가 안
# 일어난다.
#
# 프래그먼트(#...)는 URL 에서 제외한다(Finding 5) — 안 하면 같은 글이
# #comment-1 / #comment-2 처럼 프래그먼트만 다르게 나올 때 dedup 이
# 뚫린다.
_ANCHOR_TIME_RE = re.compile(r'<a\s+([^>]*)>\s*<time[^>]*datetime="([^"]+)"')
_HREF_ATTR_RE = re.compile(r'href="(/@([^/"]+)/post/([^"?#]+))(?:[?#][^"]*)?"')


def _find_permalink_time_pairs(chunk: str) -> list:
    """청크 안에서 '자기 <time> 을 바로 감싸는' 앵커 후보를 전부 찾고,
    그 중 실제로 /post/ 링크인 것만 (path, handle, id, datetime) 튜플로
    돌려준다. href 가 앵커 안 어디에 있어도 잡힌다(Finding 6)."""
    pairs = []
    for am in _ANCHOR_TIME_RE.finditer(chunk):
        attrs, posted_at = am.group(1), am.group(2)
        hm = _HREF_ATTR_RE.search(attrs)
        if hm:
            pairs.append((hm.group(1), hm.group(2), hm.group(3), posted_at))
    return pairs


# ── 리뷰 Finding 8: "확정 못 한 카드"를 원인별로 따로 센다 ──────────
# 예전엔 "ambiguous(짝 2개+)"와 "no_pairing(짝 0개)"을 하나의
# _last_dropped 로 뭉갰다. 중첩 카드 재현(리뷰어 실측)에서 청크가
# 2개 나오는데 하나는 짝 0개(그냥 continue, 카운트 안 됨), 하나는
# 짝 2개(카운트 1) — 실제로 글 2건이 사라졌는데 신호는 "1"만 남아
# 축소 보고됐다. 두 원인은 성격도 다르다: ambiguous 는 "글은 있는데
# 확정을 못 함"이고, no_pairing 은 "애초에 이 카드가 permalink+시각
# 짝 자체를 안 보여줌"이라 광고·추천계정·UI 카드도 여기 잡힌다(정상
# 피드에도 흔함 — 아래 last_no_pairing_count() docstring 참고).
_last_ambiguous = 0
_last_no_pairing = 0


def last_ambiguous_count() -> int:
    """가장 최근 parse_feed() 호출에서, 카드 안에 permalink+<time> 짝이
    2개 이상 잡혀(구조만으로 카드 자신의 글을 못 좁힘) 버려진 카드 수.
    중첩 카드(인용/리포스트)의 전형적인 증상이다 — 이 값이 0이 아니면
    실제로 글이 있는 카드를 놓쳤다는 뜻이라 신뢰할 수 있는 신호다."""
    return _last_ambiguous


def last_no_pairing_count() -> int:
    """가장 최근 parse_feed() 호출에서, permalink+<time> 짝이 아예 하나도
    안 잡힌 카드(청크) 수.

    ⚠ 이 값은 last_ambiguous_count() 보다 훨씬 노이즈가 크다 — 광고·
    추천계정·안내 카드처럼 애초에 '글'이 아닌 카드도 여기 잡히므로,
    정상적인 피드에서도 0이 아닌 게 흔하다. Task 6 은 이 값 자체를
    '이상 신호'로 알람 걸면 정상 운영 중에도 계속 울린다 — 대신
    "카드 수 대비 비율이 평소보다 갑자기 크게 뛰었는가"처럼 추세로
    보거나, last_ambiguous_count() 와 함께 참고 자료로만 쓴다. 다만
    셀렉터 자체가 깨지는 사고(예: Finding 6 류의 속성 순서 문제)가
    나면 이 값이 '거의 모든 카드'로 치솟으므로, 완전히 0건 수집인데
    이 값만 카드 수만큼 크다면 그건 실제 신호로 봐도 된다."""
    return _last_no_pairing


def parse_feed(html: str) -> list:
    """피드 HTML 에서 글 목록을 뽑는다. 못 뽑으면 빈 목록(예외 아님).

    빈 목록으로 돌려주는 이유 — 예외로 죽으면 runner 가 멈추지만,
    빈 목록이면 '3회 연속 0건 → 자동 강등' 로직이 받아 처리한다."""
    global _last_ambiguous, _last_no_pairing
    _last_ambiguous = 0
    _last_no_pairing = 0
    if not html:
        return []
    try:
        return _parse(html)
    except Exception:
        return []


def _parse(html: str) -> list:
    from html import unescape
    global _last_ambiguous, _last_no_pairing

    posts, seen = [], set()
    # 글 카드 단위로 자른다.
    chunks = html.split('data-pressable-container="true"')[1:]
    for chunk in chunks:
        pairs = _find_permalink_time_pairs(chunk)
        if not pairs:
            # 이 카드는 permalink+시각 짝 자체가 안 보인다 — 광고/UI
            # 카드일 수도, 셀렉터가 못 잡는 진짜 글일 수도 있다.
            _last_no_pairing += 1
            continue
        if len(pairs) > 1:
            # 이 청크 안에서 "카드 자신의 글"을 구조만으로 못 좁혔다.
            # 중첩 카드(인용/리포스트)의 전형적인 증상 — 오귀속시키느니
            # 버리고 셈만 남긴다.
            _last_ambiguous += 1
            continue
        path, handle, _pid, posted_at = pairs[0]
        url = THREADS_HOME + path
        if url in seen:
            continue
        seen.add(url)

        # dir="auto" 스팬들이 본문. 여러 조각으로 쪼개져 오므로 이어
        # 붙인다.
        #
        # ⚠ 리뷰 Finding 7: Round 1 에서는 알려진 UI 문구("번역 보기"
        # 등)를 조각 단위 정확 일치로 걸렀는데, 이게 실제 글 내용을
        # 지워버리는 방향으로 더 위험했다 — 본문이 여러 조각으로
        # 쪼개져 오는 게 정상이므로, "더 보기 좋은 방법 있을까요?" 가
        # "더 보기"/" 좋은 방법 있을까요?" 두 조각으로 나뉘어 오면
        # 앞 조각이 통째로 삭제되고, 글 전체가 우연히 "더보기" 한
        # 단어뿐이면 text="" 로 완전히 비어버린다. 못 거른 UI 문구가
        # 섞이는 것(under-blocking)은 LLM 이 무시하면 그만이지만, 이건
        # gate 가 점수를 매기고 reply_writer 가 참고하는 실제 원문을
        # 지우는 것(over-blocking)이라 피해가 훨씬 크고 무한하다 —
        # 실제 마크업 없이 블록리스트로 "이건 UI 문구다"를 확실히
        # 구분할 방법이 없는 이상, 아예 안 거르는 쪽이 더 안전하다.
        # 빈 조각(공백뿐인 스팬)만 제거한다 — 이건 절대 실제 내용을
        # 지우지 않는다.
        parts = re.findall(r'<span[^>]*dir="auto"[^>]*>(.*?)</span>', chunk, re.DOTALL)
        cleaned = [unescape(re.sub(r"<[^>]+>", "", p)).strip() for p in parts]
        cleaned = [t for t in cleaned if t]
        text = re.sub(r"\s{2,}", " ", " ".join(cleaned)).strip()

        # 카드 머리의 '작성자명 + 상대시각' 을 떼어낸다.
        # 실측(2026-08-04 첫 실수집): 본문이 "yonhap_news 39분 경쟁이 치열한..."
        # 처럼 들어왔다 - 작성자 링크와 시각 표시도 dir="auto" 스팬이라 본문에
        # 같이 붙는다. gate 가 점수를 매기고 LLM 이 읽는 게 원문이어야 한다.
        #
        # 위 Finding 7 의 블록리스트와 다른 점: 여기서 지우는 두 값은 추측이
        # 아니라 이 카드에서 방금 뽑아낸 자기 데이터(handle)와, 시각 표시라는
        # 위치가 고정된 패턴이다. 게다가 머리 부분에서만 뗀다 - 본문 중간의
        # 같은 문자열은 건드리지 않는다.
        text = _strip_card_header(text, handle)

        posts.append(RawPost(url=url, author=f"@{handle}",
                             text=text, posted_at=posted_at))
    return posts


# 상대시각 표시 - "39분", "3시간", "1일", "2주 전" 등. 머리에서만 뗀다.
_REL_TIME_RE = re.compile(r"^\s*\d+\s*(?:초|분|시간|일|주|개월|달|년)\s*(?:전)?\s*")


def _strip_card_header(text: str, handle: str) -> str:
    """본문 앞에 붙어 온 '작성자명 + 상대시각' 을 뗀다.

    둘 다 있을 수도, 하나만 있을 수도, 없을 수도 있어서 순서대로 한 번씩
    시도한다. 없으면 그대로 둔다 - 못 떼는 것보다 본문을 깎는 게 나쁘다."""
    if not text:
        return text
    out = text
    # 표시명이 핸들과 다를 수 있으므로 핸들로 시작할 때만 뗀다.
    if handle and out.lower().startswith(handle.lower()):
        out = out[len(handle):].lstrip()
    out = _REL_TIME_RE.sub("", out, count=1)
    # 시각이 작성자명보다 앞에 오는 배치도 있어 한 번 더 본다.
    if handle and out.lower().startswith(handle.lower()):
        out = out[len(handle):].lstrip()
    stripped = out.strip()
    # 다 떼고 나니 빈 문자열이면 원문을 돌려준다(사진만 있는 글일 수 있다).
    return stripped if stripped else text


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
