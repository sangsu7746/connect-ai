from pathlib import Path

from threads import harvester

FIXTURES = Path(__file__).parent / "fixtures"


# ── 리뷰 Round 1 Finding 1 — harvest() 는 브라우저 예외를 절대
#    밖으로 흘리면 안 된다(가짜 드라이버로, 실브라우저 없이 확인) ──
class _FakeDriver:
    """selenium 없이 harvest() 의 예외 처리 경로만 확인하기 위한 대역.
    get()/execute_script()/page_source 각각을 독립적으로 실패시킬 수 있다."""

    def __init__(self, html="", fail_get=False, fail_scroll=False,
                 fail_page_source=False):
        self._html = html
        self.fail_get = fail_get
        self.fail_scroll = fail_scroll
        self.fail_page_source = fail_page_source
        self.get_calls = 0

    def get(self, url):
        self.get_calls += 1
        if self.fail_get:
            raise TimeoutError("threads.net 응답 없음(가짜)")

    @property
    def page_source(self):
        if self.fail_page_source:
            raise RuntimeError("page_source 조회 실패(가짜)")
        return self._html

    def execute_script(self, script):
        if self.fail_scroll:
            raise RuntimeError("scroll 중 드라이버 끊김(가짜)")


class _FakeAutomator:
    """threads.automator.ThreadsAutomator 대신 주입하는 대역.
    load_session() 은 항상 성공한 걸로 치고(세션 로직은 automator 쪽
    테스트가 따로 본다), harvest() 의 수집 루프 예외 처리만 겨눈다."""

    def __init__(self, driver):
        self.driver = driver
        self.quit_called = False

    def load_session(self):
        return True

    def quit(self):
        self.quit_called = True


def _feed_html_3_posts():
    return (FIXTURES / "feed_page.html").read_text(encoding="utf-8")


def test_harvest_returns_empty_list_when_initial_navigation_raises(monkeypatch):
    """세션 로드 뒤 첫 driver.get() 이 죽어도(harvest() 자체의 최초
    이동 단계) 예외가 새어나가지 않고 빈 목록을 준다."""
    fake = _FakeAutomator(_FakeDriver(fail_get=True))
    monkeypatch.setattr(harvester, "ThreadsAutomator", lambda *a, **k: fake)
    result = harvester.harvest(limit=5)
    assert result == []
    assert fake.quit_called   # finally 경로로 quit() 은 반드시 호출돼야 한다


def test_harvest_returns_empty_list_when_page_source_raises(monkeypatch):
    """스크롤 루프 첫 회차에서 page_source 조회 자체가 죽어도(수집된
    게 하나도 없는 채로) 예외 없이 빈 목록을 준다."""
    fake = _FakeAutomator(_FakeDriver(fail_page_source=True))
    monkeypatch.setattr(harvester, "ThreadsAutomator", lambda *a, **k: fake)
    result = harvester.harvest(limit=5)
    assert result == []
    assert fake.quit_called


def test_harvest_returns_partial_results_when_scroll_raises_midloop(monkeypatch):
    """1회차에서 정상적으로 3건을 모은 뒤, 스크롤(execute_script) 이
    죽어도 지금까지 모은 3건은 그대로 살아 돌아온다 — 통째로 버리지
    않는다는 게 이 수정의 핵심."""
    fake = _FakeAutomator(_FakeDriver(html=_feed_html_3_posts(), fail_scroll=True))
    monkeypatch.setattr(harvester, "ThreadsAutomator", lambda *a, **k: fake)
    result = harvester.harvest(limit=10)
    assert len(result) == 3
    assert fake.quit_called


def _html():
    return (FIXTURES / "feed_page.html").read_text(encoding="utf-8")


def test_parse_feed_extracts_all_posts():
    posts = harvester.parse_feed(_html())
    assert len(posts) == 3


def test_parse_feed_builds_absolute_url():
    posts = harvester.parse_feed(_html())
    assert posts[0].url == "https://www.threads.net/@alice/post/AAA111"


def test_parse_feed_reads_author_and_text():
    posts = harvester.parse_feed(_html())
    assert posts[0].author == "@alice"
    assert "셀카 보정" in posts[0].text


def test_parse_feed_reads_posted_at():
    posts = harvester.parse_feed(_html())
    assert posts[0].posted_at.startswith("2026-08-03T10:00:00")


def test_parse_feed_survives_garbage():
    """DOM 이 바뀌어도 예외로 죽지 않고 빈 목록을 준다.
    죽으면 runner 가 멈추지만, 빈 목록이면 '수집 0건' 강등 로직이 받는다."""
    assert harvester.parse_feed("<html><body>nothing</body></html>") == []
    assert harvester.parse_feed("") == []


def test_parse_feed_dedupes_duplicate_urls():
    """같은 글 카드가 두 번 나와도(스크롤 겹침 등) 한 건으로 합쳐야 한다.

    기존 픽스처(feed_page.html)에는 중복 href 가 없어 이 동작을 못 잡는다.
    브리프의 '검증할 동작' 목록에 dedup 이 명시돼 있어 별도 인라인 HTML로 보강한다."""
    html = (
        '<div data-pressable-container="true">'
        '<a href="/@dave/post/DDD444" role="link">'
        '<time datetime="2026-08-03T11:00:00.000Z">10분</time></a>'
        '<span dir="auto">중복 테스트 글</span></div>'
        '<div data-pressable-container="true">'
        '<a href="/@dave/post/DDD444" role="link">'
        '<time datetime="2026-08-03T11:00:00.000Z">10분</time></a>'
        '<span dir="auto">중복 테스트 글</span></div>'
    )
    posts = harvester.parse_feed(html)
    assert len(posts) == 1


# ── 리뷰 Round 1 Finding 2 — 멘션 링크가 카드 자신의 permalink 보다
#    먼저 나와도 오귀속되면 안 된다 ──────────────────────────────
def test_parse_feed_ignores_mention_link_before_own_permalink():
    """본문 속 멘션 링크(/@남/post/...)가 카드 자신의 permalink 보다
    먼저 나오는 경우 — 첫 번째 /post/ 링크를 그냥 집으면 이 카드가
    '멘션된 사람의 글'로 둔갑하고, 이 카드의 본문·시각이 그 URL 에
    잘못 붙는다(리뷰어 재현 그대로). 카드 자신의 permalink 은
    <time datetime> 을 직접 감싸는 링크로만 식별해야 한다."""
    html = (
        '<div data-pressable-container="true">'
        '<span dir="auto">'
        '<a href="/@someoneelse/post/MENTIONED1">@someoneelse</a> 얘기 좀 그만해'
        '</span>'
        '<a href="/@alice/post/REAL1" role="link">'
        '<time datetime="2026-08-03T10:00:00.000Z">1시간</time></a>'
        '<a href="/@alice" role="link"><span>alice</span></a>'
        '</div>'
    )
    posts = harvester.parse_feed(html)
    assert len(posts) == 1
    assert posts[0].url == "https://www.threads.net/@alice/post/REAL1"
    assert posts[0].author == "@alice"


def test_parse_feed_drops_card_with_two_permalink_time_pairings():
    """카드 하나 안에서 permalink+<time> 짝이 2개 이상 잡히면(구조만으로
    어느 게 이 카드 자신의 글인지 확정할 수 없음) 아무 글도 만들지
    않고, 대신 last_dropped_count() 로 셀 수 있게 한다. 오귀속(엉뚱한
    글 URL 에 이 카드의 본문이 잘못 붙는 사고)보다 누락이 훨씬 안전하다
    (리뷰 Finding 2 의 두 번째 요구 — '모호한 카드'도 테스트)."""
    html = (
        '<div data-pressable-container="true">'
        '<a href="/@dave/post/DDD1" role="link">'
        '<time datetime="2026-08-03T09:00:00.000Z">2시간</time></a>'
        '<span dir="auto">dave 글</span>'
        '<a href="/@erin/post/EEE1" role="link">'
        '<time datetime="2026-08-03T09:30:00.000Z">1시간반</time></a>'
        '<span dir="auto">erin 글</span>'
        '</div>'
    )
    posts = harvester.parse_feed(html)
    assert posts == []
    assert harvester.last_dropped_count() == 1


# ── 리뷰 Round 1 Finding 3 — 중첩 카드(인용/리포스트)가 바깥 글을
#    삼키는 대신 눈에 보이게(드롭 카운트) 처리돼야 한다 ──────────
def test_parse_feed_nested_card_never_misattributes_and_is_counted():
    """인용/리포스트처럼 data-pressable-container 가 중첩되면, 문자열
    분할 특성상 바깥 글의 permalink 가 안쪽 청크로 흘러들어가 안쪽
    청크에 permalink+<time> 짝이 2개(자기 것 + 바깥 것) 잡힌다.
    어느 게 진짜 바깥 글인지 구조만으로 확정할 수 없으므로 드롭하고
    카운트만 남겨야 한다 — carol(안쪽) 글이 alice(바깥) 글로
    둔갑하거나 그 반대가 되는 일은 절대 없어야 한다(리뷰 재현 그대로)."""
    html = (
        '<div id="wrap">'
        '<div data-pressable-container="true">'          # 바깥(alice) 카드 시작
        '<span dir="auto">Quoted by bob</span>'
        '<div data-pressable-container="true">'           # 중첩된 안쪽(carol) 카드
        '<a href="/@carol/post/INNER1" role="link">'
        '<time datetime="2026-08-03T09:00:00.000Z">2시간</time></a>'
        '<span dir="auto">carol 의 원글</span>'
        '</div>'
        '<a href="/@alice/post/OUTER1" role="link">'      # alice 자신의 permalink(안쪽 뒤)
        '<time datetime="2026-08-03T10:00:00.000Z">1시간</time></a>'
        '<span dir="auto">alice 의 인용 코멘트</span>'
        '</div>'
        '</div>'
    )
    posts = harvester.parse_feed(html)
    # carol 의 글에 alice 의 텍스트가 붙거나 그 반대인 RawPost 는
    # 하나도 없어야 한다 — 있어도 되는 건 "아무것도 안 만듦"뿐이다.
    for p in posts:
        assert not (p.url.endswith("/INNER1") and "alice" in p.text)
        assert not (p.url.endswith("/OUTER1") and "carol" in p.text)
    assert posts == []                       # 이번 모양에서는 완전히 드롭된다
    assert harvester.last_dropped_count() == 1


# ── 리뷰 Round 1 Finding 5 (minor) — URL 프래그먼트가 dedup 을
#    뚫으면 안 된다 ─────────────────────────────────────────────
def test_parse_feed_strips_url_fragment_for_dedup():
    html = (
        '<div data-pressable-container="true">'
        '<a href="/@frank/post/FFF1#comment-1" role="link">'
        '<time datetime="2026-08-03T09:00:00.000Z">1시간</time></a>'
        '<span dir="auto">글 1</span></div>'
        '<div data-pressable-container="true">'
        '<a href="/@frank/post/FFF1#comment-2" role="link">'
        '<time datetime="2026-08-03T09:00:00.000Z">1시간</time></a>'
        '<span dir="auto">글 1 (다른 프래그먼트)</span></div>'
    )
    posts = harvester.parse_feed(html)
    assert len(posts) == 1
    assert posts[0].url == "https://www.threads.net/@frank/post/FFF1"


# ── 리뷰 Round 1 Finding 5 (minor) — 알려진 UI 문구가 본문에 안
#    섞여야 한다 ───────────────────────────────────────────────
def test_parse_feed_filters_known_ui_chrome_from_text():
    html = (
        '<div data-pressable-container="true">'
        '<a href="/@grace/post/GGG1" role="link">'
        '<time datetime="2026-08-03T09:00:00.000Z">1시간</time></a>'
        '<span dir="auto">진짜 본문입니다</span>'
        '<span dir="auto">번역 보기</span>'
        '</div>'
    )
    posts = harvester.parse_feed(html)
    assert posts[0].text == "진짜 본문입니다"
