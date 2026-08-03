from pathlib import Path

from threads import harvester

FIXTURES = Path(__file__).parent / "fixtures"


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
